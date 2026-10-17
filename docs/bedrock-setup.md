# Set up Amazon Bedrock (Amazon Nova Pro)

> **Bring your own access.** Oasis ships no API key and the authors do not provide one. The live model is optional: every feature works offline without it. If you want live extraction, planning or the chat model option (`OASIS_CHAT_LLM=1`), you need your own AWS account with Bedrock model access to Amazon Nova Pro, you pay AWS directly for the tokens used, and you supply credentials through the standard AWS chain (profile, role, environment variables or `AWS_BEARER_TOKEN_BEDROCK` in your git-ignored `.env`). Set a spend alarm and keep `OASIS_BEDROCK_DAILY_TOKENS` low first.

Oasis runs offline by default. These steps turn on the live model (`OASIS_LLM=bedrock`). The planner (2026-10-13), vision, extraction and the LLM risk scorer (2026-10-17) have each been run live on Amazon Nova Pro in small samples (see results.md); do step 6 to confirm your own account before relying on it.

1. **AWS account and region.** Sign in to the AWS console and pick a region that offers Amazon Nova Pro (for example `us-east-1`).
2. **Enable the model.** Bedrock console > Model access (or Model catalog) > request access to Amazon Nova Pro. Wait until the status says Access granted.
3. **Copy the exact model id.** Bedrock console > Model catalog (or Inference profiles) > Amazon Nova Pro. Use the id or inference-profile id it shows, for example `us.amazon.nova-pro-v1:0`. The repo default `us.amazon.nova-pro-v1:0` worked in our runs on a US-region account; your account may need a different id or inference profile.
4. **Give credentials a minimal IAM policy.** Create an IAM user (or SSO role) with only:
   ```json
   {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
     "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"], "Resource": "*"}]}
   ```
   Converse calls need `bedrock:InvokeModel`. With an inference profile, also allow the underlying foundation-model ARNs (Resource `*` covers it while testing).
5. **Put credentials on this machine** (never in the repo). Either a Bedrock API key, which boto3 reads from `AWS_BEARER_TOKEN_BEDROCK`, or an IAM access key:
   ```
   $env:AWS_BEARER_TOKEN_BEDROCK="..."; $env:AWS_REGION="us-east-1"      # Bedrock API key (needs a recent boto3)
   ```
   or:
   ```
   pip install -r requirements.txt            # installs boto3
   aws configure                              # access key, secret, region (needs the AWS CLI), or:
   $env:AWS_ACCESS_KEY_ID="..."; $env:AWS_SECRET_ACCESS_KEY="..."; $env:AWS_REGION="us-east-1"
   ```
   Then copy `.env.example` to `.env` and set `OASIS_LLM=bedrock` and `OASIS_BEDROCK_MODEL=<id from step 3>`.
6. **Smoke test with a tiny call, then the benchmark:**
   ```
   PYTHONPATH=. python -c "from oasis.agent.llm import LiveLLM; print(LiveLLM()._chat('Reply with one word.', 'ping'))"
   PYTHONPATH=. python -m eval.runner --llm bedrock --extract llm --repeats 1
   ```
   Errors name the cause: `AccessDeniedException` (model access or IAM), `ResourceNotFoundException` / "model identifier is invalid" (wrong id or region), `NoCredentialsError` (step 5).
7. **Cap the spend.** `OASIS_BEDROCK_DAILY_TOKENS` (default 2,000,000, about $1 at $0.10 in / $0.50 out per 1M tokens) stops the app after that many tokens a day. Also add an AWS Budgets alert (Billing > Budgets) at your test budget.
8. **Run the app live:** `OASIS_LLM=bedrock OASIS_EXTRACT=llm uvicorn oasis.api.main:app`. Keep `OASIS_LLM=offline` for tests and for any public instance you do not want to pay for: live mode sends typed text to Bedrock on your account. The authors' hosted demo runs live with a daily token cap and an offline fallback (see docs/deployment-docker.md section 6).
