import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
MODELS = [                                                                                                                                    
    {                                                 
        "id": "gpt-5",
        "label": "Standard",                                                                                                                  
        "caption": "Best accuracy · Recommended default",
    },                                                                                                                                        
    {                                                 
        "id": "gpt-5-mini",                                                                                                                   
        "label": "Fast draft",
        "caption": "Cheap & quick · Good for routine filings",                                                                                
    },                                                                                                                                        
    {
        "id": "o3",                                                                                                                           
        "label": "Deep analysis",                     
        "caption": "Reasons step-by-step · Multi-clause conflicts, complex briefs",
    },                                                                                                                                        
    {
        "id": "gpt-4.1",                                                                                                                      
        "label": "Long document",                     
        "caption": "1M token context · For 200+ page filings",                                                                                
    },                                                                                                                                        
]
