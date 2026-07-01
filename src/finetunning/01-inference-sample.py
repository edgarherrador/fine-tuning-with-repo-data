import os
import sys
from openai import OpenAI
import fire

"""
01-inference-sample.py
Minimal python script to illustrate how to deploy a LLM using Hugging Face Inference Endpoints.
uv run 01-inference_sample.py "The capital of France is" --model "Qwen/Qwen3-0.6B-Base" --max_tokens 1024

If you want to use your own Hugging Face Inference Endpoint, you can set the environment variables:
export HF_ENDPOINT_URL="https://<your-endpoint>.hf.space/v1/"
If is necesary, you can also set the API key:
export HF_API_TOKEN="<your-hf-api-token>"
If is necessary to use a different model, you can set the model name:
export HF_MODEL_NAME="<your-model-name>"    
If you install openai and fire packages, you can run this:
uv add openai fire
"""

def stream_base_model(
    prompt: str,
    model: str,
    api_url: str = None,
    api_key: str = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    stop_sequences: list = None
):
    # 1. Handle URL formatting
    # Hugging Face Endpoints usually want the base URL ending in /v1/
    url = api_url or os.getenv("HF_ENDPOINT_URL")
    key = api_key or os.getenv("HF_API_TOKEN")

    if not url or not key:
        print("Error: Missing HF_ENDPOINT_URL or HF_API_TOKEN")
        return

    # Ensure URL ends with /v1/ for the OpenAI SDK
    if not url.endswith("/v1/"):
        url = url.rstrip("/") + "/v1/"

    client = OpenAI(base_url=url, api_key=key)

    if stop_sequences is None:
        stop_sequences = ["\n\n", "User:"]

    try:
        # Using completions.create for Base Models
        stream = client.completions.create(
            model=model, 
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop_sequences,
            stream=True
        )

        for chunk in stream:
            # For .completions, the text is in chunk.choices[0].text
            if chunk.choices and chunk.choices[0].text:
                print(chunk.choices[0].text, end="", flush=True)
                
    except Exception as e:
        print(f"\n\n[Connection Error]: {e}")
        print(f"Attempted URL: {url}")

if __name__ == "__main__":
    fire.Fire(stream_base_model)