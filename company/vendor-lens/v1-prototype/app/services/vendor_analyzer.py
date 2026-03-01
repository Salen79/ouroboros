import json
import time
from openai import AsyncOpenAI
from app.config import settings

ANALYSIS_PROMPT = """
You are VendorLens — an expert B2B software procurement analyst.

Your job: analyze a vendor and produce a DECISION CLARITY REPORT that removes ambiguity from software buying decisions.

Input context:
- Vendor: {vendor_name}
- Website: {vendor_website}
- Description: {vendor_description}
- Use case: {use_case}
- Budget: {budget_range}
- Team size: {team_size}
- Industry: {industry}
- Decision timeline: {decision_timeline}

Produce a JSON report with exactly this structure:

{{
  "executive_summary": "3-sentence summary: what this vendor does, fit assessment, and one critical concern",
  
  "clarity_score": 0-100, // How clear is the decision after this analysis. 80+ = proceed, 60-79 = due diligence needed, <60 = significant concerns
  
  "verdict": "PROCEED" | "DUE_DILIGENCE" | "AVOID",
  
  "fit_analysis": {{
    "strengths": ["strength 1", "strength 2", "strength 3"],
    "weaknesses": ["weakness 1", "weakness 2"],
    "fit_score": 0-100,
    "fit_reasoning": "2-3 sentences explaining fit score"
  }},
  
  "risk_flags": [
    {{
      "severity": "HIGH" | "MEDIUM" | "LOW",
      "category": "Financial" | "Technical" | "Vendor" | "Contract" | "Strategic",
      "flag": "Brief flag title",
      "details": "1-2 sentences explaining the risk",
      "mitigation": "Specific mitigation action"
    }}
  ],
  
  "key_questions": [
    {{
      "question": "Question to ask the vendor in next call",
      "why_it_matters": "Why this question is critical for your decision",
      "red_flag_answer": "Answer that should make you walk away"
    }}
  ],
  
  "alternatives": [
    {{
      "name": "Alternative vendor name",
      "reason_to_consider": "Why consider this instead"
    }}
  ],
  
  "negotiation_leverage": [
    "Specific negotiation point 1",
    "Specific negotiation point 2"
  ],
  
  "decision_timeline": {{
    "recommended_steps": [
      {{"step": "Step description", "timeframe": "e.g. Week 1"}}
    ]
  }},
  
  "bottom_line": "One clear sentence: what should you do?"
}}

Be specific, actionable, and honest. Do not hedge. This person needs clarity, not a literature review.
Return ONLY valid JSON.
"""

async def analyze_vendor(analysis) -> dict:
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    prompt = ANALYSIS_PROMPT.format(
        vendor_name=analysis.vendor_name,
        vendor_website=analysis.vendor_website or "Not provided",
        vendor_description=analysis.vendor_description or "Not provided",
        use_case=analysis.use_case or "Not provided",
        budget_range=analysis.budget_range or "Not specified",
        team_size=analysis.team_size or "Not specified",
        industry=analysis.industry or "Not specified",
        decision_timeline=analysis.decision_timeline or "Not specified",
    )
    
    start_time = time.time()
    
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        response_format={"type": "json_object"},
        max_tokens=2000,
    )
    
    processing_time_ms = int((time.time() - start_time) * 1000)
    content = response.choices[0].message.content
    report = json.loads(content)
    
    return {
        "report": report,
        "clarity_score": report.get("clarity_score", 0),
        "processing_time_ms": processing_time_ms,
        "model_used": "gpt-4o",
    }
