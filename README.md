# ECS Cost Analysis

A Python script to analyze ECS clusters for excess resources and then approximate the cost of those excess resources.

## Approach

1) Iterate through each AWS account.
2) Describe all ECS container instances and tasks.
3) Print the task with the largest CPU value and the task with the largest memory value.
4) Print all unique CPU and memory values across tasks in a cluster.
5) Calculate the total available CPU and memory in the cluster and the CPU and memory used by tasks.
6) Excess CPU and memory is total available minus used.
7) Calculate the number of instances (e.g., `c5.2xlarge`) we can fit within the excess.
8) Estimate potential savings via the number of excess instances.
9) Display the aggregate of potential savings across all AWS accounts.
## Usage

First, enter a Python 3 virtual environment and install dependencies:

```console
python3 -m venv ./.venv
source ./.venv/bin/activate
pip install -r requirements.txt
```

Next, run the script, passing each AWS profile you'd like to include in the analysis:

```console
./ecs_cost_analysis --aws-profiles \
    apollo.admin \
    acqa.admin \
    qa.admin \
    mapping.admin \
    fdp.admin \
    acprod.admin \
    prod.admin
```

It may be helpful to refresh your SSO session beforehand. For example:

```console
aws sso login --sso-session rocky 
```
