K8s Cluster (A running cluster isn't expected):
* Create a Kubernetes cluster using Terraform, containing instance groups with both on-demand and spot instances.
* The node groups should be compatible with Cluster Autoscaler.

Infra: 
* Create a Kubernetes deployment containing an Nginx and a web application; the web application statics(CSS, JS, etc.) files should be served directly via Nginx with shared storage.
* Expose the Deployment via a Kubernetes Service.
* Implement auto-scaling.
* Implement configuration via ConfigMap and Secret.
* Use Helm to render the Kubernetes templates, it should be re-usable across multiple environments.
 
Development:
* Develop a web application (using Python, Node.js, or Go) to parse and process the CSV file attached format. You can print each line on the browser when processing the file.
* The web application should have an interface to upload CSV and show previously processed files.
* Upload the CSV file to the s3 storage once it is processed. 
* A transition from S3 to Glacier is expected on the S3 config.

Notes:
* You can use Minukube to deploy locally
* You can use DockerHub to store Docker images
* You can use GitHub to store application and infra codes

Attachment: soh.csv

Solution:
* Documentation and architecture diagram
* Git history with meaningful process messages
* Automated test
* CI/CD pipelines
