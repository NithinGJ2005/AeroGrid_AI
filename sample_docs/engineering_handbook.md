# Engineering Standards and Architecture Handbook

## 1. Source Control and Branching Policy
All software engineering repositories follow the GitHub Flow branching strategy. Direct commits to `main` or `production` branches are strictly blocked by branch protection rules. Every pull request requires at least one peer code review and passing automated CI/CD checks before merge.

## 2. Secure Coding and Secrets Management
Hardcoding secrets, API keys, passwords, or private certificates in code repositories is strictly prohibited. All configuration must be provided via environment variables or fetched from the internal secret manager. Pre-commit hooks run secret detection tools before any commit is accepted.

## 3. Container Image Signing & Deployment
All production containers must be built using approved base images from the internal private container registry. Images must be signed using Cosign/Notary, and deployment pipelines verify cryptographic signatures before deploying to Kubernetes or Podman clusters.
