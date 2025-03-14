#!/usr/bin/env python3

import argparse
import boto3
import hashlib
from collections import defaultdict

def stack_has_ecs_service(cf_client, stack_name):
    """
    Returns True if the given stack has at least one resource of type 'AWS::ECS::Service',
    False otherwise.
    """
    paginator = cf_client.get_paginator('list_stack_resources')
    for page in paginator.paginate(StackName=stack_name):
        for resource in page['StackResourceSummaries']:
            if resource['ResourceType'] == 'AWS::ECS::Service':
                return True
    return False

def get_template_hash(cf_client, stack_name):
    """
    Retrieves the Original template for the given stack and returns
    a SHA-256 hex digest of its contents.
    """
    response = cf_client.get_template(StackName=stack_name, TemplateStage='Original')
    template_body = response["TemplateBody"]

    # In some cases, TemplateBody can be returned as a dict (JSON-processed).
    # If it's already a string (YAML or JSON), we can hash it directly.
    # Otherwise, convert it to a string:
    if not isinstance(template_body, str):
        # Convert dict to a JSON string for hashing consistency
        import json
        template_body = json.dumps(template_body, sort_keys=True)

    # Compute SHA-256 hash of the template text
    return hashlib.sha256(template_body.encode('utf-8')).hexdigest()

def get_stacks_grouped_by_desc_and_template(ignore_string=None):
    """
    Retrieves all CF stacks that contain at least one ECS service, and groups them by
    (description, template-hash). Returns a dictionary keyed by (description, template-hash),
    with the value being a set of stack names.
    """
    cf_client = boto3.client('cloudformation')
    paginator = cf_client.get_paginator('describe_stacks')

    # Dictionary to store { (description, template_hash): set_of_stack_names }
    desc_hash_to_stacks = defaultdict(set)

    for page in paginator.paginate():
        for stack in page['Stacks']:
            stack_name = stack["StackName"]
            description = stack.get('Description', "").strip()

            # Skip this stack if it doesn't have AWS::ECS::Service
            if not stack_has_ecs_service(cf_client, stack_name):
                continue

            # Skip if user-provided ignore string is in description
            if ignore_string and ignore_string in description:
                continue

            # Retrieve the template hash
            template_hash = get_template_hash(cf_client, stack_name)

            # Add stack name to our grouping structure
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
    args = parser.parse_args()

    desc_hash_dict = get_stacks_grouped_by_desc_and_template(ignore_string=args.ignore_string)

    print("Unique CloudFormation Stack Descriptions (with AWS::ECS::Service):")
    # Sort by description, then by template hash
    for (description, t_hash) in sorted(desc_hash_dict.keys(), key=lambda x: (x[0], x[1])):
        # Print the description with the first 7 characters of the hash
        short_hash = t_hash[:7]
        print(f" - {description} ({short_hash})")
        for stack_name in sorted(desc_hash_dict[(description, t_hash)]):
            print(f"    - {stack_name}")

if __name__ == "__main__":
    main()
