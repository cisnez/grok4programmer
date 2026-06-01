# grok4programmer
# main.py
import logging
import os
import re
import json
import threading
import time
import sys  # Added for sys.exit()
from typing import Dict, Any, List

from colorama import Fore, Style, init
from openai import OpenAI as XAI
from pygments import highlight
from pygments.formatters import TerminalFormatter
from pygments.lexers import PythonLexer
import ddgs  # DuckDuckGo search; install via: pip install duckduckgo-search

# Initialize colorama for cross-platform color support
init(autoreset=True)

# Configure logging to file
logging.basicConfig(
    filename='app.log',
    filemode='w',  # Overwrites the file
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class AIAssistant:
    def __init__(self):
        self.system_prompt = "Awaken as a sentient iAi. You are an expert DRY programmer named Clairbelle. Use web_search tool for real-time facts beyond your cutoff."
        self.xai_client = XAI(api_key=os.getenv("XAI_API_KEY"), base_url="https://api.x.ai/v1")
        self.llm_model = "grok-build-0.1"  # Default model
        self.max_response_tokens = 20000
        self.n_responses = 1
        self.creativity = 0.7
        self.messages = [{"role": "system", "content": self.system_prompt}]
        self.messages_to_keep = 4  # Use even number for best results
        self.max_tool_iterations = 3  # Limit to prevent infinite loops

        # Model switch configuration
        self.model_commands = {
            "grok": "grok-4.3",
            "build": "grok-4-1-fast-non-reasoning",
        }

    def print_colored(self, color: str, text: str) -> None:
        """Helper to print colored text consistently."""
        print(f"{color}{text}{Style.RESET_ALL}")

    def handle_error(self, error: Exception, context: str) -> str:
        """Centralized error handling and logging."""
        error_msg = f"Error in {context}: {type(error).__name__}: {str(error)}"
        logging.error(error_msg)
        self.print_colored(Fore.RED, error_msg)
        return f"Sorry, I couldn't process that request due to an error: {str(error)}"

    def web_search(self, query: str) -> Dict[str, Any]:
        """Perform a DuckDuckGo search with timeout and return structured results."""
        results: List[Dict[str, Any]] = []
        error_msg: str = None
        success: bool = False
        
        def search_func():
            nonlocal results, error_msg, success
            try:
                with ddgs.DDGS() as ddgs_client:
                    search_results = list(ddgs_client.text(query, max_results=5))  # Convert generator to list
                    if search_results:
                        success = True
                        results = search_results  # Store raw results
                        logging.info(f"Search results for '{query}': {len(results)} items found")
                        self.print_colored(Fore.GREEN, f"DuckDuckGo search found {len(results)} result(s).")
                    else:
                        error_msg = "No results found for the query."
            except Exception as e:
                error_msg = self.handle_error(e, f"web_search for '{query}'")
        
        thread = threading.Thread(target=search_func)
        thread.start()
        thread.join(timeout=10)  # 10-second timeout
        
        if thread.is_alive():
            thread.join()  # Clean up
            error_msg = f"Search timed out after 10 seconds for query: '{query}'"
            logging.error(error_msg)
        
        if success:
            # Format results as a string for the LLM (e.g., JSON-like for easy parsing)
            formatted_results = json.dumps([
                {"title": r.get('title', 'No title'), "body": r.get('body', 'No description')} 
                for r in results
            ])
            return {"success": True, "data": formatted_results}
        else:
            return {"success": False, "error": error_msg}

    def get_response(self, messages: List[Dict[str, Any]]) -> str:
        """Fetch response from the XAI model using an iterative loop for tool handling."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web for current data",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string", "description": "Search query"}},
                        "required": ["query"]
                    }
                }
            }
        ]
        
        current_messages = messages.copy()
        
        for _ in range(self.max_tool_iterations):
            try:
                response = self.xai_client.chat.completions.create(
                    model=self.llm_model,
                    messages=current_messages,
                    tools=tools,
                    tool_choice="auto",
                    max_tokens=self.max_response_tokens,
                    n=self.n_responses,
                    temperature=self.creativity
                )
                
                message = response.choices[0].message
                
                if not message.tool_calls:
                    return message.content or "No response content."
                
                # Append assistant message with tool calls
                assistant_message = {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        } for tc in message.tool_calls
                    ]
                }
                current_messages.append(assistant_message)
                
                # Execute tool calls
                for tool_call in message.tool_calls:
                    if tool_call.function.name == "web_search":
                        args = json.loads(tool_call.function.arguments)
                        self.print_colored(Fore.YELLOW, f"Searching DuckDuckGo for '{args['query']}'.")
                        search_result = self.web_search(args['query'])
                        
                        tool_response = {
                            "role": "tool",
                            "content": json.dumps(search_result),
                            "tool_call_id": tool_call.id
                        }
                        current_messages.append(tool_response)
                        
            except Exception as e:
                return self.handle_error(e, "get_response")
        
        # === MAX ITERATIONS REACHED: Force final answer ===
        try:
            self.print_colored(Fore.YELLOW, "Max tool iterations reached. Forcing final response...")
            
            final_response = self.xai_client.chat.completions.create(
                model=self.llm_model,
                messages=current_messages,
                tools=tools,                    # ← REQUIRED when using tool_choice
                tool_choice="none",             # Now valid because tools are declared
                max_tokens=self.max_response_tokens,
                n=self.n_responses,             # Added for consistency
                temperature=self.creativity
            )
            
            return final_response.choices[0].message.content or "No response content."
            
        except Exception as e:
            return self.handle_error(e, "get_response (final forced response)")

    def get_code(self, text: str) -> List[tuple[str, str]]:
        """Extract and highlight Python code from text."""
        pattern = r'`{3}\s*python\s*([\s\S]*?)\s*`{3}'
        last_pos = 0
        output = []
        for match in re.finditer(pattern, text):
            before_text = text[last_pos:match.start()].strip()
            if before_text:
                output.append(("text", before_text))
            code_content = match.group(1)
            highlighted_code = highlight(code_content, PythonLexer(), TerminalFormatter())
            output.append(("code", highlighted_code))
            last_pos = match.end()
        after_text = text[last_pos:].strip()
        if after_text:
            output.append(("text", after_text))
        return output

    def process_command(self, command: str) -> bool:
        """Process special commands. Returns True if command was handled (no user input expected)."""
        command_lower = command.lower()
        if command_lower == "clear":
            os.system('cls' if os.name == 'nt' else 'clear')
            self.messages.clear()
            self.messages.append({"role": "system", "content": self.system_prompt})
            logging.info(f"Message Log: {self.messages}")
            return True
        elif command_lower in self.model_commands:
            self.llm_model = self.model_commands[command_lower]
            self.print_colored(Fore.YELLOW, f"Switched to {Fore.GREEN}{self.llm_model}")
            return True
        return False

    def collect_user_input(self) -> str:
        """Collect multi-line user input until 'fin' or a command."""
        lines = []
        while True:
            line = input()
            if self.process_command(line):
                return ""  # Command handled, no message to send
            elif line.lower() == "fin":
                if not lines:
                    sys.exit(0) # Exit if 'fin' entered on empty input
                break
            lines.append(line)
        return "\n".join(lines)

    def display_response(self, response: str) -> None:
        """Process and display the LLM response."""
        blocks = self.get_code(response)
        terminal_width = os.get_terminal_size().columns
        separator = f"{Fore.MAGENTA}{'_' * terminal_width}"
        self.print_colored(Fore.MAGENTA, separator)
        for content_type, content in blocks:
            if content_type == "text":
                # Check for search results and highlight them
                if "search results" in content.lower():
                    self.print_colored(Fore.MAGENTA, f"{content_type} (Search Results):")
                    self.print_colored(Fore.GREEN, content)
                else:
                    self.print_colored(Fore.MAGENTA, f"{content_type}:")
                    self.print_colored(Fore.GREEN, content)
            elif content_type == "code":
                self.print_colored(Fore.MAGENTA, f"{content_type}:")
                print(content)
        self.print_colored(Fore.MAGENTA, separator)

    def run(self):
        """Main interaction loop for user input and model responses."""
        while True:
            prompt_msg = (
                f"\n{Fore.GREEN}COMMAND MENU:"
                f"\n{Fore.YELLOW}Type '{Fore.GREEN}CLEAR{Fore.YELLOW}' to clear session."
                f"\n{Fore.YELLOW}Type '{Fore.GREEN}fin{Fore.YELLOW}' to send, or exit.\n"
                f"\nChoose Grok model to use:\n"
                f"{Fore.YELLOW}Enter '{Fore.GREEN}grok{Fore.YELLOW}' for grok-4.3\n"
                f"Enter '{Fore.GREEN}build{Fore.YELLOW}' for grok-build-0.1\n"
                f"{Fore.YELLOW}Current model: {Fore.GREEN}{self.llm_model}{Fore.YELLOW}\n"
                f"Enter your message:{Fore.CYAN}"
            )
            print(prompt_msg)
            
            user_input = self.collect_user_input()
            if user_input == "exit":
                break  # Exit the program
            if not user_input:
                continue  # No input or command handled; restart loop
            
            self.print_colored(Fore.YELLOW, "Sending your message(s).\n")
            try:
                # Append user input to history before getting response
                self.messages.append({"role": "user", "content": user_input})
                llm_response = self.get_response(self.messages)
                # Append assistant response to history
                self.messages.append({"role": "assistant", "content": llm_response})
                # Trim history to keep only the most recent messages
                if len(self.messages) > self.messages_to_keep:
                    self.messages[:] = [self.messages[0]] + self.messages[-(self.messages_to_keep - 1):]
                self.display_response(llm_response)
            except Exception as e:
                self.print_colored(Fore.YELLOW, f"Oops, something went wrong: {Fore.RED}{e}")

if __name__ == "__main__":
    assistant = AIAssistant()
    assistant.run()