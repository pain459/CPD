FROM node:20-alpine AS build
WORKDIR /ui
COPY package.json vite.config.js index.html ./
COPY src ./src
RUN npm install && npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /ui/dist /usr/share/nginx/html
EXPOSE 80
