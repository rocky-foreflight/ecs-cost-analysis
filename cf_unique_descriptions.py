#!/usr/bin/env python3

import argparse
import boto3
import hashlib
import json
from collections import defaultdict

def stack_has_ecs_service(cf_client, stack_name):
    """
    Returns True if the given stack has at least one resource of type 'AWS::ECS::Service'.
    """
    paginator = cf_client.get_paginator('list_stack_resources')
    for page in paginator.paginate(StackName=stack_name):
        for resource in page['StackResourceSummaries']:
            if resource['ResourceType'] == 'AWS::ECS::Service':
                return True
    return False

def get_template_body_string(cf_client, stack_name):
    """
    Retrieves the original template for the given stack, returning it as a string.
    If the TemplateBody is already a string, we return it directly.
    If it's a dict, we serialize it to JSON for consistency.
    """
    response = cf_client.get_template(StackName=stack_name, TemplateStage='Original')
    template_body = response["TemplateBody"]

    if isinstance(template_body, dict):
        # Convert dictionary to JSON
        return json.dumps(template_body, sort_keys=True)
    else:
        # YAML or JSON string as-is
        return template_body

def compute_template_hash(template_str):
    """
    Computes an SHA-256 hex digest from the provided template string.
    """
    return hashlib.sha256(template_str.encode('utf-8')).hexdigest()

def get_stacks_grouped_by_desc_and_template(ignore_string=None, contains_string=None):
    """
    Retrieves all CF stacks that contain at least one ECS service. Then:
      1) Filters out descriptions containing 'ignore_string' if provided.
      2) Only processes the stack if the template body contains 'contains_string' (if provided).
      3) Groups them by (description, template-hash).
    Returns a dictionary keyed by (description, template-hash), with the value being a set of stack names.
    """
    cf_client = boto3.client('cloudformation')
    paginator = cf_client.get_paginator('describe_stacks')

    desc_hash_to_stacks = defaultdict(set)

    for page in paginator.paginate():
        for stack in page['Stacks']:
            stack_name = stack["StackName"]
            description = stack.get('Description', "").strip()

            # Skip stacks without ECS services
            if not stack_has_ecs_service(cf_client, stack_name):
                continue

            # Skip if user-provided ignore_string is in description
            if ignore_string and ignore_string in description:
                continue

            # Retrieve the template as a string
            template_str = get_template_body_string(cf_client, stack_name)

            # If --contains-string is specified, only process if template contains the substring
            if contains_string and contains_string not in template_str:
                continue

            # Compute the hash if we haven't skipped
            template_hash = compute_template_hash(template_str)

            # Group by (description, template_hash)
            desc_hash_to_stacks[(description, template_hash)].add(stack_name)

    return desc_hash_to_stacks

def main():
    parser = argparse.ArgumentParser(
        description="Lists CF stacks (with ECS::Service) grouped by description and template hash."
    )
    parser.add_argument(
        "--ignore-string", "-i",
        default=None,
        help="Ignore any descriptions that contain this string."
    )
    parser.add_argument(
        "--contains-string", "-c",
        default=None,
        help="Only process stacks whose template contains this substring."
    )
    args = parser.parse_args()

    desc_hash_dict = get_stacks_grouped_by_desc_and_template(
        ignore_string=args.ignore_string,
        contains_string=args.contains_string
    )

    print("Unique CloudFormation Stack Descriptions (with AWS::ECS::Service):")
    # Sort by description, then by template hash
    for (description, t_hash) in sorted(desc_hash_dict.keys(), key=lambda x: (x[0], x[1])):
        short_hash = t_hash[:7]
        print(f" - {description} ({short_hash})")
        for stack_name in sorted(desc_hash_dict[(description, t_hash)]):
            print(f"    - {stack_name}")

if __name__ == "__main__":
    main()
