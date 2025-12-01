```
##Feature Folder Description

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
