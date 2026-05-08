ARG BUILDPLATFORM
ARG TARGETPLATFORM

# Build the static assets on the build platform (avoids QEMU arm64 issues).
FROM --platform=$BUILDPLATFORM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json* /app/
RUN npm ci

COPY . /app/
RUN npm run build


FROM --platform=$TARGETPLATFORM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

