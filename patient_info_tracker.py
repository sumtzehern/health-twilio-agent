# patient_info_tracker.py
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams

# Machine‐readable schema we give to the LLM:
collect_patient_info_schema = FunctionSchema(
    name="collect_patient_info",
    description="Extract any patient fields from the last user utterance",
    properties={
        "name":        {"type": "string", "description": "Patient's full name"},
        "dob":         {"type": "string", "description": "Date of birth, e.g. YYYY-MM-DD"},
        "insurance_provider": {"type": "string"},
        "insurance_id":       {"type": "string"},
        "referral":  {"type": "string"},
        "chief_complaint": {"type": "string"},
        "address":   {"type": "string"},
        "phone":     {"type": "string"},
        "email":     {"type": "string"},
        "appointment": {"type": "object",
            "properties": {
                "doctor_name": {"type":"string"},
                "date":        {"type":"string"},
                "time":        {"type":"string"}
            }
        },
    },
    required=[]  # we let the model omit any it doesn’t see
)

# ToolsSchema so the context knows about it:
patient_tools = ToolsSchema(standard_tools=[collect_patient_info_schema])


async def collect_patient_info(params: FunctionCallParams):
    """
    params.arguments is already a dict of fields extracted by the LLM.
    Just hand it over to your tracker.
    """
    args: dict = params.arguments
    tracker = params.user_data["patient_tracker"] 
    for field, val in args.items():
        if val == "declined":
            tracker.mark_declined(field)
        elif val:
            tracker.update_field(field, val)

    # you must invoke the callback so that the pipeline knows
    # "the function has returned" and can resume generation.
    await params.result_callback({"updated": list(args.keys())})
