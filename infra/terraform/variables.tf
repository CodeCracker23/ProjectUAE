variable "region" {
  type        = string
  default     = "us-east-1"
  description = "AWS region"
}

variable "cluster_name" {
  type        = string
  default     = "soh-eks"
  description = "EKS cluster name"
}

variable "s3_bucket_name" {
  type        = string
  default     = "soh-files-bucket"
  description = "S3 bucket for CSV files"
}

variable "vpc_id" {
  type        = string
  default     = "vpc-xxxxxxxx"
  description = "Existing VPC ID (replace)"
}

variable "private_subnet_ids" {
  type        = list(string)
  default     = ["subnet-aaaaaa", "subnet-bbbbbb", "subnet-cccccc"]
  description = "Private subnet IDs for EKS"
}

variable "on_demand_instance_types" {
  type        = list(string)
  default     = ["t3.medium"]
  description = "Instance types for on-demand node group"
}

variable "spot_instance_types" {
  type        = list(string)
  default     = ["t3.small", "t3.medium"]
  description = "Instance types for spot node group"
}

variable "desired_on_demand_size" {
  type        = number
  default     = 2
  description = "Desired size for on-demand node group"
}

variable "desired_spot_size" {
  type        = number
  default     = 2
  description = "Desired size for spot node group"
}
