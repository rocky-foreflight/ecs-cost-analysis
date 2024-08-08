import argparse
import datetime
import sys

import boto3

ecs_client = boto3.client("ecs")
ec2_client = boto3.client("ec2")
sts_client = boto3.client("sts")
organizations_client = client = boto3.client("organizations")

# Instance data for m5 family
instance_data = {
    "m5.large": {"cost": 0.096, "vcpus": 2, "memory_gib": 8},
    "m5.xlarge": {"cost": 0.192, "vcpus": 4, "memory_gib": 16},
    "m5.2xlarge": {"cost": 0.384, "vcpus": 8, "memory_gib": 32},
    "m5.4xlarge": {"cost": 0.768, "vcpus": 16, "memory_gib": 64},
}


def get_caller_identity():
    response = sts_client.get_caller_identity()
    return response


def describe_account(account_id):
    response = organizations_client.describe_account(AccountId=account_id)
    return response["Account"]


def list_container_instances(cluster_name):
    response = ecs_client.list_container_instances(cluster=cluster_name)
    return response["containerInstanceArns"]


def describe_container_instances(cluster_name, container_instance_arns):
    response = ecs_client.describe_container_instances(cluster=cluster_name, containerInstances=container_instance_arns)
    return response["containerInstances"]


def list_tasks(cluster_name):
    response = ecs_client.list_tasks(cluster=cluster_name)
    return response["taskArns"]


def describe_tasks(cluster_name, task_arns):
    response = ecs_client.describe_tasks(cluster=cluster_name, tasks=task_arns)
    return response["tasks"]


def calculate_current_usage(container_instances):
    total_cpu = 0
    total_memory = 0
    used_cpu = 0
    used_memory = 0

    for instance in container_instances:
        total_cpu += instance["registeredResources"][0]["integerValue"]
        total_memory += instance["registeredResources"][1]["integerValue"]

        used_cpu += (
            instance["registeredResources"][0]["integerValue"] - instance["remainingResources"][0]["integerValue"]
        )
        used_memory += (
            instance["registeredResources"][1]["integerValue"] - instance["remainingResources"][1]["integerValue"]
        )

    return total_cpu, total_memory, used_cpu, used_memory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cluster_name")
    parser.add_argument("instance_type")
    args = parser.parse_args()

    cluster_name = args.cluster_name
    instance_type = args.instance_type

    caller_identity = get_caller_identity()
    account_id = caller_identity["Account"]
    account_name = describe_account(account_id)["Name"]

    print(f"{datetime.datetime.now(datetime.timezone.utc)}:")
    print(f"  {"cluster name":<12} : {cluster_name} ECS cluster")
    print(f"  {"account":<12} : {account_name} ({account_id})")
    print()

    # Get the task with the largest CPU allocation and the task with the largest memory allocation
    task_arns = list_tasks(cluster_name)
    tasks = describe_tasks(cluster_name, task_arns)

    largest_cpu_task = max(tasks, key=lambda x: int(x["cpu"]))
    largest_memory_task = max(tasks, key=lambda x: int(x["memory"]))

    print(f"{instance_type} CPU units: {instance_data[instance_type]["vcpus"] * 1024}")
    print(f"{instance_type} memory: {instance_data[instance_type]["memory_gib"] * 1024}")
    print()

    print(f"Largest task CPU units: {int(largest_cpu_task["cpu"])}")
    print(f"Largest task memory: {int(largest_memory_task["memory"])}")
    print()

    # Unique values are interesting because we can see values that aren't multiples of 1024 and thus can never fit
    # evenly into a container instance
    unique_cpu_values = {int(task["cpu"]) for task in tasks}
    unique_memory_values = {int(task["memory"]) for task in tasks}

    print(f"Unique CPU unit values: {unique_cpu_values}")
    print(f"Unique memory values: {unique_memory_values}")
    print()

    # Get the total CPU and memory and current usage, then calculate excess
    container_instance_arns = list_container_instances(cluster_name)
    container_instances = describe_container_instances(cluster_name, container_instance_arns)

    total_cpu, total_memory, used_cpu, used_memory = calculate_current_usage(container_instances)

    print(f"Total vCPUs: {total_cpu / 1024:.0f}, Total Memory: {total_memory / 1024:.0f} GiB")
    print(f"Used vCPUs: {used_cpu / 1024:.0f}, Used Memory: {used_memory / 1024:.0f} GiB")

    excess_cpu = total_cpu - used_cpu
    excess_memory = total_memory - used_memory

    print(f"Excess vCPUs: {excess_cpu / 1024:.0f}, Excess Memory: {excess_memory / 1024:.0f} GiB")
    print()

    # Calculate the number of instances that fit within the excess resources
    num_instances_fit_within_excess_cpu = excess_cpu / (instance_data[instance_type]["vcpus"] * 1024)
    num_instances_fit_within_excess_memory = excess_memory / (instance_data[instance_type]["memory_gib"] * 1024)

    # Use the larger number of instances
    num_excess_instances = max(num_instances_fit_within_excess_cpu, num_instances_fit_within_excess_memory)

    current_cost_hourly = len(container_instances) * instance_data[instance_type]["cost"]
    potential_savings_hourly = num_excess_instances * instance_data[instance_type]["cost"]

    print(f"Current Cost: ${current_cost_hourly:.0f}/hr OR ${current_cost_hourly * 730:.0f}/mo")
    print(f"An excess of {num_excess_instances:.1f} {instance_type} instances worth of compute")
    print(f"Potential Savings: ${potential_savings_hourly:.0f}/hr OR ${potential_savings_hourly * 730:.0f}/mo")

    return 0


if __name__ == "__main__":
    sys.exit(main())
