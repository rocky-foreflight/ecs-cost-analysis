#!/usr/bin/env python3

import argparse
import boto3

def normalize_ecs_service_arn(service_arn: str, fallback_cluster_name: str) -> str:
    """
    Normalize an ECS service ARN so that it includes the cluster name in its path.
    If the original ARN is already the long/new format, return it as-is.
    Otherwise, insert fallback_cluster_name into the ARN.

    Examples:
      Old/short format:
        arn:aws:ecs:REGION:ACCOUNT_ID:service/MyService
        --> arn:aws:ecs:REGION:ACCOUNT_ID:service/MyCluster/MyService

      New/long format:
        arn:aws:ecs:REGION:ACCOUNT_ID:service/MyCluster/MyService
        --> (unchanged)
    """
    parts = service_arn.split(":")
    if len(parts) < 6:
        return service_arn  # Malformed, just return it unchanged

    region = parts[3]
    account_id = parts[4]

    resource_part = parts[5]  # e.g. "service/MyService" or "service/MyCluster/MyService"
    resource_parts = resource_part.split("/")

    if len(resource_parts) < 2:
        # Not what we expect; return unchanged
        return service_arn
    if resource_parts[0] != "service":
        # Not an ECS service ARN
        return service_arn

    # Old/short format => ["service", "MyService"]
    if len(resource_parts) == 2:
        service_name = resource_parts[1]
        cluster_name = fallback_cluster_name
    # New/long format => ["service", "MyCluster", "MyService"]
    elif len(resource_parts) == 3:
        cluster_name = resource_parts[1]
        service_name = resource_parts[2]
    else:
        # Unexpected number of segments; return as-is
        return service_arn

    # Reconstruct the "long" ARN
    normalized = f"arn:aws:ecs:{region}:{account_id}:service/{cluster_name}/{service_name}"
    return normalized

def main():
    parser = argparse.ArgumentParser(
        description="List ECS EC2 services in a given cluster that are NOT managed by any CloudFormation stack."
    )
    parser.add_argument(
        "--cluster",
        required=True,
        help="The name of the ECS cluster to inspect."
    )
    args = parser.parse_args()
    cluster_name = args.cluster

    ecs_client = boto3.client('ecs')
    cfn_client = boto3.client('cloudformation')

    # 1. Get ARNs of all ECS services in the cluster
    service_arns = []
    next_token = None
    while True:
        list_kwargs = {
            'cluster': cluster_name,
            'maxResults': 100
        }
        if next_token:
            list_kwargs['nextToken'] = next_token

        response = ecs_client.list_services(**list_kwargs)
        service_arns.extend(response["serviceArns"])
        next_token = response.get("nextToken")
        if not next_token:
            break

    print(f"Found {len(service_arns)} total services (all launch types) in ECS cluster '{cluster_name}'.")

    # 2. Describe these services to get their launchType
    service_launch_types = {}
    BATCH_SIZE = 10
    for i in range(0, len(service_arns), BATCH_SIZE):
        batch = service_arns[i : i + BATCH_SIZE]
        describe_resp = ecs_client.describe_services(cluster=cluster_name, services=batch)
        for svc in describe_resp.get("services", []):
            service_launch_types[svc["serviceArn"]] = svc.get("launchType", "UNKNOWN")

    # 3. Filter for only EC2 services, normalizing their ARNs
    ec2_services = set()
    for original_arn, lt in service_launch_types.items():
        if lt == "EC2":
            norm_arn = normalize_ecs_service_arn(original_arn, cluster_name)
            ec2_services.add(norm_arn)

    print(f"Of those, {len(ec2_services)} have launchType=EC2.")

    # 4. List CloudFormation stacks (ignore those in DELETE_COMPLETE)
    stack_arns = []
    next_token = None
    while True:
        list_kwargs = {}
        if next_token:
            list_kwargs['NextToken'] = next_token

        response = cfn_client.list_stacks(**list_kwargs)
        for summary in response["StackSummaries"]:
            # Skip stacks with status DELETE_COMPLETE
            if summary["StackStatus"] == "DELETE_COMPLETE":
                continue
            stack_arns.append(summary["StackId"])

        next_token = response.get("NextToken")
        if not next_token:
            break

    print(f"Found {len(stack_arns)} CloudFormation stacks (excluding DELETE_COMPLETE).")

    # 5. Gather all ECS services from CFN, normalized
    cfn_ec2_services = set()
    for stack_arn in stack_arns:
        try:
            resources = cfn_client.describe_stack_resources(StackName=stack_arn)
            for resource in resources.get("StackResources", []):
                if resource["ResourceType"] == "AWS::ECS::Service":
                    raw_arn = resource["PhysicalResourceId"]
                    norm_arn = normalize_ecs_service_arn(raw_arn, cluster_name)
                    cfn_ec2_services.add(norm_arn)
        except Exception as e:
            print(f"Warning: Could not describe resources for stack {stack_arn}. Error: {str(e)}")

    # Restrict to services that actually appear in ec2_services (i.e., in this cluster, launchType=EC2)
    cfn_ec2_services_in_cluster = cfn_ec2_services.intersection(ec2_services)

    print(f"Found {len(cfn_ec2_services_in_cluster)} ECS EC2 services in cluster '{cluster_name}' that appear in CFN.")

    # 6. Compute those that are in ECS (EC2) but NOT in CFN
    unmanaged_ec2_services = ec2_services - cfn_ec2_services_in_cluster

    # 7. Print results
    if unmanaged_ec2_services:
        print(f"\nEC2-based ECS services in cluster '{cluster_name}' NOT managed by any CloudFormation stack:")
        for svc in sorted(unmanaged_ec2_services):
            print(f"  {svc}")
    else:
        print(f"\nAll EC2-based ECS services in cluster '{cluster_name}' are managed by CloudFormation stacks.")

if __name__ == "__main__":
    main()
