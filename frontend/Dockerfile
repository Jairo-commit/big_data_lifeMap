# Frontend de LifeMap: se construye con pnpm y se sirve con nginx, que también reenvía /api a la API.
FROM node:24-alpine AS build
WORKDIR /app
# pnpm viene con corepack, en la versión que fija "packageManager" de package.json
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginx:1.27-alpine
# El entrypoint de nginx sustituye las variables de entorno en las plantillas de /etc/nginx/templates
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
ENV API_UPSTREAM=http://api:5000
EXPOSE 80
