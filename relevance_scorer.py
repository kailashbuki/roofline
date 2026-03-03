import re
from datetime import datetime

def calculate_relevance(title, summary, keywords_config):
    text = f"{title} {summary}".lower()
    
    high_value = keywords_config.get('high_value_keywords', [])
    bonus = keywords_config.get('bonus_keywords', [])
    
    score = 0.0
    
    # Higher weight for high-value keywords
    for keyword in high_value:
        if keyword.lower() in text:
            score += 0.25
    
    # Bonus keywords
    for keyword in bonus:
        if keyword.lower() in text:
            score += 0.15
    
    # Extra boost for arXiv papers with specific inference terms
    arxiv_boost_terms = ['inference', 'serving', 'deployment', 'optimization', 'acceleration', 
                         'quantization', 'compression', 'efficient', 'fast', 'latency', 'throughput']
    if any(term in text for term in arxiv_boost_terms):
        score += 0.2
    
    # Boost for hardware-specific content
    hardware_terms = ['gpu', 'tpu', 'neuron', 'trainium', 'cuda', 'tensor core']
    if any(term in text for term in hardware_terms):
        score += 0.15
    
    return min(score, 1.0)

def extract_tags(title, summary):
    text = f"{title} {summary}".lower()
    tags = []
    
    tag_keywords = {
        'quantization': ['quantization', 'int8', 'int4', 'fp16', 'bfloat16', 'gptq', 'awq', 'gguf'],
        'inference': ['inference', 'serving', 'deployment', 'vllm', 'tensorrt', 'tgi'],
        'optimization': ['optimization', 'speedup', 'acceleration', 'latency', 'throughput'],
        'attention': ['attention', 'kv cache', 'flash attention', 'paged attention'],
        'compression': ['compression', 'pruning', 'distillation', 'sparsity'],
        'hardware': ['gpu', 'cuda', 'tensor core', 'tpu', 'neuron', 'trainium'],
        'multimodal': ['vision language', 'vlm', 'multimodal', 'audio language'],
        'llm': ['llm', 'language model', 'gpt', 'llama', 'mistral']
    }
    
    for tag, keywords in tag_keywords.items():
        if any(kw in text for kw in keywords):
            tags.append(tag)
    
    return ','.join(tags)
