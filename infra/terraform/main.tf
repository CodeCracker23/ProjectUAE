terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

locals {
  cluster_name = var.cluster_name
}

resource "aws_s3_bucket" "csv" {
  bucket = var.s3_bucket_name
  lifecycle_rule {
    id      = "transition-glacier"
    enabled = true
    transition {
      days          = 30
      storage_class = "GLACIER"
    }
  }
  versioning {
    enabled = true
  }
}

# Placeholder for EKS cluster, node groups (on-demand + spot), IRSA, etc.
# Would include aws_eks_cluster, aws_eks_node_group resources compatible with cluster-autoscaler labels.
module "eks" {
  source          = "terraform-aws-modules/eks/aws"
  version         = "~> 20.0"
  cluster_name    = local.cluster_name
  cluster_version = "1.29"
  vpc_id          = var.vpc_id
  subnet_ids      = var.private_subnet_ids

  enable_irsa = true

  eks_managed_node_groups = {
    on_demand = {
      instance_types = var.on_demand_instance_types
      capacity_type  = "ON_DEMAND"
      desired_size   = var.desired_on_demand_size
      min_size       = 1
      max_size       = 5
      labels = {
        lifecycle = "OnDemand"
      }
      taints = []
    }
    spot = {
      instance_types = var.spot_instance_types
      capacity_type  = "SPOT"
      desired_size   = var.desired_spot_size
      min_size       = 1
      max_size       = 10
      labels = {
        lifecycle = "Ec2Spot"
      }
      taints = []
    }
  }

  # Tags recognized by cluster-autoscaler to discover ASGs/NodeGroups
  tags = {
    "k8s.io/cluster-autoscaler/enabled"        = "true"
    "k8s.io/cluster-autoscaler/${local.cluster_name}" = "owned"
  }
}
