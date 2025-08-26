# Architecture Diagram

```mermaid
graph TD;
  User[Browser] -->|Upload CSV| NginxSidecar[Nginx Sidecar]
  NginxSidecar -->|Reverse Proxy /| AppPod[FastAPI App]
  AppPod -->|Write CSV| SharedVolume[(Shared Volume)]
  NginxSidecar -->|Serve static + /data| SharedVolume
  AppPod -->|Upload| S3[(S3 Bucket)]
  S3 -->|Lifecycle 30d->Glacier| Glacier[(Glacier)]
  AppPod --> SQLite[(SQLite DB PVC/emptyDir)]
  subgraph Kubernetes
    AppPod
    NginxSidecar
    SharedVolume
  end
  subgraph AWS
    S3
    Glacier
  end
  Terraform --> EKS[(EKS Cluster + NodeGroups)]
  EKS --> ClusterAutoscaler[Cluster Autoscaler]
  ClusterAutoscaler --> NodeGroups[(On-Demand & Spot)]
```

## Notes
- Terraform defines S3 bucket (with lifecycle) and EKS skeleton.
- Helm deploys app + sidecar + optional PVC + autoscaler.
- SQLite persistence stored on PVC when enabled.
