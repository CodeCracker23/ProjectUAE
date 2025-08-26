# SOH CSV Processor Case Study

## Overview
This repository contains a reference implementation for the DevOps case study:
- FastAPI web application for uploading and processing CSV files.
- CSV files stored locally then uploaded to S3 with a lifecycle transition to Glacier (Terraform bucket rule).
- Kubernetes deployment with sidecar Nginx serving static/shared data volume.
- Helm chart to deploy application with autoscaling, ConfigMap, Secret.
- Terraform skeleton for AWS (S3 + placeholder for EKS cluster, on-demand & spot node groups).
- Basic automated test and Dockerfile.

## Architecture
[Detailed diagram](./docs/architecture.md)
Components:
1. User uploads CSV via FastAPI
2. Application parses CSV, stores locally (shared volume), indexes metadata in memory
3. File uploaded to S3 bucket (lifecycle -> Glacier after 30 days)
4. Nginx sidecar serves /data directory for static access
5. HPA auto-scales app based on CPU

## Local Development
```powershell
cd app
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Docker Build
docker build -t your-dockerhub-username/soh-processor:latest .
```powershell
cd app
docker build -t mrashidoner/soh-processor:latest .
```

## Helm Deploy (after pushing image)
```powershell
helm upgrade --install soh ./infra/helm/chart --set image.repository=mrashidoner/soh-processor
```

## Terraform (S3 only placeholder)
```powershell
cd infra/terraform
terraform init
terraform apply -auto-approve
```

## Testing
```powershell
cd app
pytest -q
```

## Next Steps / Enhancements
- Implement persistence layer (e.g., PostgreSQL or DynamoDB) for metadata.
- Finalize EKS (currently skeleton) with real VPC + subnets + IRSA + cluster-autoscaler deployment (already templated in Helm).
- Replace placeholder AWS credentials Secret with IRSA.
- Add integration tests and GitHub Actions CI/CD workflows.
- Add nginx.conf ConfigMap mount and static asset pipeline.

## Configuration Matrix
Helm `values.yaml` parameters (selected):
- `image.repository`, `image.tag` – container image
- `autoscaling.*` – HPA settings
- `probes.readiness.*`, `probes.liveness.*` – health probe tuning
- `persistence.enabled` – enable PVC for SQLite & shared data
- `persistence.size`, `persistence.storageClass`, `persistence.existingClaim`
- `clusterAutoscaler.enabled` – toggle autoscaler manifest
- `clusterAutoscaler.image.*`, `clusterAutoscaler.extraArgs`

## Requirement Coverage
- Terraform S3 + lifecycle (Glacier transition) and EKS skeleton with on-demand + spot groups tags for autoscaler
- Helm: Deployment (app + nginx), Service, HPA, ConfigMap, Secret, optional PVC, Autoscaler
- App: Upload + parse CSV, list processed, view rows, download original, S3 upload (skips w/o creds), structured logging
- Tests: health + upload (extendable)
- CI: build, test, docker push workflow
- Docs: architecture diagram, README

## Running Locally
```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r app/requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Helm Quickstart
```powershell
helm upgrade --install soh ./infra/helm/chart \
	--set image.repository=mrashidoner/soh-processor \
	--set persistence.enabled=true
```
"
