# Deployment

## Local development

See README (uvicorn + Vite) or `docker compose up --build` (mock + DRY_RUN, ports bound to 127.0.0.1).

## Real Air France mode — keep it local

Manual login needs a **visible** browser on your own machine. Recommended: backend locally
(`PROVIDER=airfrance`, `BROWSER_HEADLESS=false`), optionally frontend locally too.
A cloud container cannot host your interactive login safely; do not upload browser sessions.

## Microsoft Foundry / Azure OpenAI

1. In a Foundry project, deploy a chat model supporting structured outputs (JSON schema).
2. Set `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_KEY`
   (or adapt `AzureOpenAIClient` to managed identity), `AZURE_FOUNDRY_PROJECT` for reference.
3. The dashboard then shows "LLM Azure". If Azure fails, the deterministic engine decides alone.

## Azure Container Apps (mock / demo / dashboard)

```bash
az group create -n rg-air-upgrade -l westeurope
az acr create -n <acr> -g rg-air-upgrade --sku Basic
az acr build -r <acr> -t air-upgrade-backend:0.1 -f backend/Dockerfile .
az acr build -r <acr> -t air-upgrade-frontend:0.1 frontend
az containerapp env create -n cae-air-upgrade -g rg-air-upgrade -l westeurope
az containerapp create -n air-upgrade-backend -g rg-air-upgrade --environment cae-air-upgrade \
  --image <acr>.azurecr.io/air-upgrade-backend:0.1 --registry-server <acr>.azurecr.io \
  --ingress internal --target-port 8000 \
  --secrets azure-openai-key=<key> \
  --env-vars DRY_RUN=true PROVIDER=mock AZURE_OPENAI_API_KEY=secretref:azure-openai-key \
             AZURE_OPENAI_ENDPOINT=<endpoint> AZURE_OPENAI_DEPLOYMENT=<deployment>
az containerapp create -n air-upgrade-frontend -g rg-air-upgrade --environment cae-air-upgrade \
  --image <acr>.azurecr.io/air-upgrade-frontend:0.1 --registry-server <acr>.azurecr.io \
  --ingress external --target-port 80
```

Notes: the frontend nginx proxies `/api` to host `backend` — set the backend app name/FQDN accordingly
in `frontend/nginx.conf`. Protect the dashboard (Container Apps built-in authentication / Entra ID):
it exposes the confirmation buttons. Use Azure Files or PostgreSQL Flexible Server for persistence.

## Azure App Service

Deploy the backend image as a Web App for Containers (`WEBSITES_PORT=8000`), app settings as above
(Key Vault references for secrets), enable App Service Authentication, and host the frontend `dist/`
on Static Web Apps with an API link to the backend.
