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
    If the TemplateBody is already a string, return it directly.
    If it's a dict, serialize it to JSON for consistency.
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
    """Computes an SHA-256 hex digest from the provided template string."""
    return hashlib.sha256(template_str.encode('utf-8')).hexdigest()

def get_stacks_grouped_by_desc_and_template(ignore_string=None, contains_string=None, ignore_stack_prefixes=None):
    """
    Retrieves all CF stacks that contain at least one ECS service. Then:
      1) Filters out descriptions containing 'ignore_string' if provided.
      2) Only processes the stack if the template body contains 'contains_string' (if provided).
      3) Groups them by (description, template-hash).

    Returns a dict keyed by (description, template_hash),
    whose value is a list of (stack_name, last_updated_str) tuples.
    """
    cf_client = boto3.client('cloudformation')
    paginator = cf_client.get_paginator('describe_stacks')

    # Dictionary { (description, template_hash): [(stack_name, last_updated_str), ...] }
    desc_hash_to_stacks = defaultdict(list)
    total_matched = 0

    for page in paginator.paginate():
        for stack in page['Stacks']:
            stack_name = stack["StackName"]
            description = stack.get('Description', "").strip()

            if ignore_stack_prefixes and any(stack_name.startswith(prefix) for prefix in ignore_stack_prefixes):
                continue

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

            # Compute the template hash
            template_hash = compute_template_hash(template_str)

            # Determine the "last updated" string
            # If 'LastUpdatedTime' is missing, we say "never updated"
            last_updated_time = stack.get('LastUpdatedTime')
            if last_updated_time:
                last_updated_str = last_updated_time.strftime('%Y-%m-%d %H:%M:%S')
            else:
                last_updated_str = "never updated"

            # Append (stack_name, last_updated_str) to the group
            desc_hash_to_stacks[(description, template_hash)].append((stack_name, last_updated_str))
            total_matched += 1

    return desc_hash_to_stacks, total_matched

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
    parser.add_argument(
        "--ignore-prefix", action='append', default=[],
        help="Ignore stacks with names starting with this prefix. Can be specified multiple times."
    )
    parser.add_argument(
        "--template-names-only",
        action='store_true',
        help="Only print unique template descriptions and hashes (hides individual stacks)."
    )
    args = parser.parse_args()

    desc_hash_dict, total_matched = get_stacks_grouped_by_desc_and_template(
        ignore_string=args.ignore_string,
        contains_string=args.contains_string,
        ignore_stack_prefixes=args.ignore_prefix
    )

    print(f"ECS-service stacks matched after filters: {total_matched}\n")
    # Sort by description, then by template hash
    for (description, t_hash) in sorted(desc_hash_dict.keys(), key=lambda x: (x[0], x[1])):
        short_hash = t_hash[:7]
        print(f" - {description} ({short_hash})")

        # Unless --template-names-only was requested, list individual stacks
        if not args.template_names_only:
            # Sort stacks by name for consistent output
            stacks_info = sorted(desc_hash_dict[(description, t_hash)], key=lambda x: x[0])
            for stack_name, last_updated_str in stacks_info:
                print(f"    - {stack_name} (Last updated: {last_updated_str})")

if __name__ == "__main__":
    main()
