# Quantifying the Performance Cost of API Security in Cloud-Native Microservices

This repository contains the complete experimental testbed, configuration manifests, and load testing scripts used in the empirical study: **"Quantifying the Performance Cost of API Security in Cloud-Native Microservices: An Empirical Study of TLS, mTLS, and JWT Validation."**

The project benchmarks the latency and CPU impact of progressively layering security mechanisms (Edge TLS, Istio mTLS, and Application-layer JWT) in a Kubernetes environment.

## 📂 Project Structure

The repository is organized to facilitate the reproducibility of the five experimental scenarios:
```

TWO-SERVICES-API/
├── kubernetes/
│   ├── istio-1.28.0/               # Service Mesh installation files
│   ├── destination-rule.yaml       # Client-side mTLS configuration (ISTIO_MUTUAL)
│   ├── ingress.yaml                # NGINX Ingress routing rules (Edge TLS)
│   ├── mtls-policy.yaml            # PeerAuthentication policy (STRICT mode)
│   ├── service-a-deployment.yaml   # Deployment spec for Service A
│   ├── service-a-service.yaml      # Service definition for Service A
│   ├── service-b-deployment.yaml   # Deployment spec for Service B
│   └── service-b-service.yaml      # Service definition for Service B
├── load-tests/
│   ├── test.js                     # Baseline load test (Scenario 1)
│   ├── test-tls.js                 # Edge TLS load test (Scenario 2 & 3)
│   └── test-jwt.js                 # JWT load test (Scenario 4 & 5)
├── results/                        # Raw data logs from experiments
│   ├── scenario1_baseline/
│   ├── scenario2_edgetls/
│   ├── scenario3_mtls/
│   ├── scenario4_jwt/
│   └── scenario5_fullstack/
├── service-a/                      # Source code for Service A
│   ├── index.js                    # Main app logic (includes JWT validation)
│   ├── create-token.js             # Utility to generate test tokens
│   └── Dockerfile                  # Container build instructions
├── service-b/                      # Source code for Service B
│   ├── index-b.js                  # Main app logic (Review service)
│   └── Dockerfile                  # Container build instructions
└── tls-cert/                       # Self-signed certificates for Edge TLS

```

## Prerequisites
To replicate these experiments, you need the following tools installed:

  - Docker Desktop (with Kubernetes enabled)
  - Kubectl (Command-line tool for Kubernetes)
  - Istio CLI (v1.28.0 or compatible)
  - k6 (Open-source load testing tool)
  - Node.js (Only if you wish to modify the source code locally)

## Setup & Installation
1. Clone the Repository
  ``` git clone [https://github.com/Katha-Sikdar/microservices-api.git](https://github.com/Katha-Sikdar/microservices-api.git)```
  ``` cd microservices-api ```

2. Install Istio Service Mesh - 
    ``` istioctl install --set profile=demo -y```
    ```kubectl label namespace default istio-injection=enabled ```

3. Deploy Infrastructure and Services
Apply the Kubernetes manifests to deploy the microservices, ingress controller, and security policies.
``` kubectl apply -f kubernetes/service-a-deployment.yaml```
``` kubectl apply -f kubernetes/service-a-service.yaml ```
``` kubectl apply -f kubernetes/service-b-deployment.yaml ```
``` kubectl apply -f kubernetes/service-b-service.yaml ```
``` kubectl apply -f kubernetes/ingress.yaml ```

4. Enforce Zero Trust Policies (For Scenarios 3 & 5)
Apply the strict mTLS policies to lock down the mesh.
```kubectl apply -f kubernetes/mtls-policy.yaml ```
``` kubectl apply -f kubernetes/destination-rule.yaml ```

## Reproducing the Experiments
We used k6 running on the host machine to generate a consistent load (100 VUs, Closed-loop).

Scenario 1: Baseline (Plain HTTP)
Prerequisite: Disable ```mtls-policy.yaml``` and remove TLS from Ingress.
``` k6 run load-tests/test.js```
Scenario 2 & 3: Edge TLS and Full mTLS
Prerequisite: Ensure ```tls-cert``` secret is created in Kubernetes.
``` # Note: --insecure-skip-tls-verify is required for self-signed certs```
``` k6 run --insecure-skip-tls-verify load-tests/test-tls.js```
Scenario 4 & 5: JWT Validation (Full Stack)
Prerequisite: Service-A must be running the image with JWT logic enabled.
``` k6 run --insecure-skip-tls-verify load-tests/test-jwt.js ```

## Key Configurations
- mTLS Enforcement: Defined in ```kubernetes/mtls-policy.yaml``` using ```mode: STRICT```.

- JWT Algorithm: HS256 (HMAC SHA-256) implemented in ```service-a/index.js```.

- Load Profile: 100 Virtual Users with a 1-second sleep timer, configured in ```load-tests/test.js```.

## License
- This project is open-sourced for academic and research purposes.
