# Set up Amazon Bedrock (Amazon Nova Pro)

Oasis runs offline by default. These steps turn on the live model (`OASIS_LLM=bedrock`). Nothing here has been run against the real API yet, so do step 6 before relying on it.

1. **AWS account and region.** Sign in to the AWS console and pick a region that offers Amazon Nova Pro (for example `us-east-1`).
2. **Enable the model.** Bedrock console > Model access (or Model catalog) > request access to Amazon Nova Pro. Wait until the status says Access granted.
3. **Copy the exact model id.** Bedrock console > Model catalog (or Inference profiles) > Amazon Nova Pro. Use the id or inference-profile id it shows, for example `us.amazon.nova-pro-v1:0`. The default in this repo is a guess.
4. **Give credentials a minimal IAM policy.** Create an IAM user (or SSO role) with only:
   ```json
   {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
     "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"], "Resource": "*"}]}
   ```
   Converse calls need `bedrock:InvokeModel`. With an inference profile, also allow the underlying foundation-model ARNs (Resource `*` covers it while testing).
5. **Put credentials on this machine** (never in the repo):
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
8. **Run the app live:** `OASIS_LLM=bedrock OASIS_EXTRACT=llm uvicorn oasis.api.main:app`. Keep `OASIS_LLM=offline` for tests and any public instance: live mode sends typed text to Bedrock on your account.
