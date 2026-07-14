import json, base64, os
from pipeline.module2_validator import run_module2

img_path='test_screen.png'
if not os.path.exists(img_path):
    raise SystemExit('test_screen.png missing in backend/')
with open(img_path,'rb') as f:
    img_b64=base64.standard_b64encode(f.read()).decode('utf-8')
module1_output={
    'ticket_id':'PROJ-42',
    'enriched_acceptance_criteria':["Email input field must be labeled Email","Password input field must be labeled Password"],
    'design_images':[img_b64]
}
res=run_module2(module1_output)
print(json.dumps(res,indent=2))
with open('module2_output.json','w') as f:
    json.dump(res,f,indent=2)
print('Saved module2_output.json')
