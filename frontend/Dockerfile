FROM node:20-alpine

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm install

COPY frontend/ ./

ENV NEXT_TELEMETRY_DISABLED=1
EXPOSE 3030
CMD ["npm", "run", "dev", "--", "--port", "3030", "--hostname", "0.0.0.0"]
