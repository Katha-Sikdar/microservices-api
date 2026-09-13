# Dockerfile for the S8 and S9 scenario services.
#
# Build context is the ARTIFACT ROOT, not scenarios/, because the services load
# ../instrumentation/eventloop-metrics.js and that path has to survive into the
# image unchanged. Both scenarios share one image; which service runs is chosen
# by the Deployment's command, so S8 and S9 differ by a command-line argument
# rather than by a build.
#
# Base image and dependency ranges are deliberately identical to
# microservices-api/service-a/Dockerfile. S8 and S9 are compared against S5, and
# a different Node minor or Express patch inside that comparison is exactly the
# kind of confound the single-image PSAO_AUTH_MODE switch exists to avoid.
FROM node:18-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install --omit=dev

COPY instrumentation/ ./instrumentation/
COPY scenarios/ ./scenarios/

EXPOSE 3000 9464

# Overridden per scenario by the Deployment.
CMD [ "node", "scenarios/s8-token-cache.js" ]
