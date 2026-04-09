from google.adk.agents import LlmAgent, SequentialAgent, LoopAgent
from google.adk.tools import FunctionTool, exit_loop
from pydantic import BaseModel
from typing import List
import os

# --- 1. JAVA SPECIFIC SCHEMAS ---
class StackFrame(BaseModel):
    class_name: str
    method_name: str
    file_name: str
    line_number: int

class ExceptionDetail(BaseModel):
    unique_id: str
    language: str = "Java"
    exception_string: str
    stack_trace: List[StackFrame]

# --- 2. THE FILE READER TOOL ---
def read_java_source(file_name: str) -> str:
    """
    Locates and reads a Java source file by searching the parallel 'src' directory.
    """
    # 1. Get path to traceai/agents/exception_classifier_agent/
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 2. Go up two levels to reach traceai/ and then into source_code/
    project_src_dir = os.path.abspath(os.path.join(current_script_dir, "..", "..", "source_code"))
    
    target_path = None

    # 3. Walk through traceai/src to find the file
    for root, dirs, files in os.walk(project_src_dir):
        if file_name in files:
            target_path = os.path.join(root, file_name)
            break

    # 4. Handle results
    if not target_path:
        return (f"RESULT: NOT_FOUND. File '{file_name}' not found in '{project_src_dir}'. "
                "It may be an external library or JDK class.")
    
    try:
        with open(target_path, "r") as f:
            content = f.read()
            return f"--- FILE: {target_path} ---\n{content}"
    except Exception as e:
        return f"RESULT: ERROR reading file: {str(e)}"


# --- 3. AGENTS ---

model="gemini-2.5-flash-lite"

# Agent 1: The Java Parser
parser_agent = LlmAgent(
    name="exception_parser",
    model=model,
    description="Parses Java exceptions into detailed structured JSON.",
    instruction="""
    ROLE: You are a strict Java Exception Parser.
    
    GUARDRAIL: 
    - Do not entertain general conversation, questions, or non-Java code.
    - If it IS a Java exception, extract:
        - Extract the following from the Java stack trace:
        - unique_id, language, and the exception string.
        - For each line in the trace, extract the class name, method name, source file name, and the line number.
        - Keep the frames in the order they appear (most recent call first).
    """,
    output_schema=ExceptionDetail, 
    output_key="parsed_exception" 
)

# Agent 2: The Iterative Researcher
researcher_agent = LlmAgent(
    name="researcher_agent",
    model=model,
    tools=[FunctionTool(read_java_source), exit_loop],
    instruction="""
    
    Review the frames in {parsed_exception}.
    
    1. Start at the first frame. Use 'read_java_source' to see if you can access the code.
    2. If the tool returns 'NOT_FOUND', it's a library; move to the NEXT frame in the trace.
    3. If you find a file that EXISTS, analyze it. If you can explain the bug, call 'exit_loop'.
    4. If you've checked 5 project files and still can't find the root cause, call 'exit_loop'.
    
    Keep track of which frame you are on using the session state.
    """,
    output_key="found_code_context"
)

# Agent 3: The Java Fixer
fix_agent = LlmAgent(
    name="java_fix_suggester",
    model=model,
    instruction="""
    
    Using the stack trace {parsed_exception} and the source code found: {found_code_context}
    
    Explain the Java error (e.g., NPE, OutOfBounds) and provide the fixed code block.
    """
)

# --- 4. THE SEQUENTIAL WORKFLOW ---
root_agent = SequentialAgent(
    name="java_debug_pipeline",
    sub_agents=[
        parser_agent,
        LoopAgent(name="trace_walker", sub_agents=[researcher_agent], max_iterations=3),
        fix_agent
    ]
)
