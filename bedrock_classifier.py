import boto3
import json

def classify_article(title, summary):
    """Use Bedrock GPT-OSS 20B to classify article relevance."""
    
    session = boto3.Session(profile_name='bis')
    bedrock = session.client('bedrock-runtime', region_name='us-west-2')
    
    prompt = f"""Is this article about inference optimization of foundation models on AI accelerators?

Title: {title}
Summary: {summary}

Answer with JSON only:
{{"relevant": true/false, "score": 0.0-1.0, "tags": ["tag1", "tag2"]}}

Tags can be: quantization, inference, optimization, attention, compression, hardware, multimodal, llm"""

    try:
        response = bedrock.invoke_model(
            modelId='amazon.gpt-oss-20b-instruct-v1:0',
            body=json.dumps({
                "inputText": prompt,
                "textGenerationConfig": {
                    "maxTokenCount": 100,
                    "temperature": 0.1,
                    "topP": 0.9
                }
            }),
            performanceConfig={
                "serviceTier": "flex"
            }
        )
        
        result = json.loads(response['body'].read())
        text = result['results'][0]['outputText'].strip()
        
        # Parse JSON response
        data = json.loads(text)
        
        if not data.get('relevant', False):
            return 0.0, ""
        
        score = data.get('score', 0.5)
        tags = ','.join(data.get('tags', []))
        
        return score, tags
        
    except Exception as e:
        print(f"Bedrock error: {e}")
        # Fallback to keyword-based
        from relevance_scorer import calculate_relevance, extract_tags
        score = calculate_relevance(title, summary, {
            'high_value_keywords': ['inference', 'optimization', 'accelerator'],
            'bonus_keywords': ['quantization', 'gpu', 'tpu']
        })
        tags = extract_tags(title, summary)
        return score, tags
