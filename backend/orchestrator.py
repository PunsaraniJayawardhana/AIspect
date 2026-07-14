# backend/orchestrator.py (relevant section)

from pipeline.module2_validator import run_module2

def run_pipeline(ticket_id: str):
    # ... Module 1 runs first ...
    module1_output = run_module1(ticket_id)  # your teammate's function
    
    # Module 2
    module2_output = run_module2(module1_output)
    
    # Save output for debugging and Module 3 handoff
    with open(f"output/module2_fixtures/{ticket_id}_module2.json", "w") as f:
        import json
        json.dump(module2_output, f, indent=2)
    
    # ... Module 3 receives module2_output["high_confidence"] ...