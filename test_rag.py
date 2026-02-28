import os
from ai.config import AIConfig
from ai.agents.orchestrator import AgentOrchestrator

def run_test():
    print("Initializing Orchestrator...")
    orchestrator = AgentOrchestrator()
    print("Orchestrator Initialized.")
    
    # 1. Provide a scenario query
    query = "Generate a robust login feature for the demoqa application that tests both valid and invalid scenarios. Use standard selenium/playwright practices."
    print(f"\nProcessing query: {query}")
    
    # 2. Test intent detection
    print("\n--- Testing Intent Agent ---")
    intent = orchestrator.intent_agent.classify(query)
    print(f"Detected Intent: {intent.intent}")
    
    # 3. Test execution and Retrieval
    print("\n--- Testing RAG Execution & Generation ---")
    state = orchestrator.run(query)
    
    plan = orchestrator.planner.build_plan(intent, query)
    print(f"Proposed Plan Steps: {[step.name for step in plan]}")
    
    if "context" in state:
         context_str = str(state['context'])
         print(f"\nRAG Retrieved Context (Length: {len(context_str)} characters).")
         print(f"Snippet:\n{context_str[:200]}...\n")
    
    if "generate_feature" in state:
        print("\n--- Generation Output Success ---")
        print("Pipeline managed to fetch context and hit OpenAI effectively.")
        print("\nPreview of Generated File Content:")
        print(str(state["generate_feature"])[:600] + "\n...")
        print("\nPIPELINE TEST SUCCESSFUL! 🎉")
    else:
        print("Pipeline failed to produce expected output.")
        print("State contents: ", state.keys())

if __name__ == '__main__':
    run_test()
