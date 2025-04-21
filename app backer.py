import os
import gradio as gr
import anthropic
import requests
import json
from datetime import datetime
from typing import Dict, List, Any

# Initialize the Anthropic client
# Note: In production, API key should be passed as an environment variable
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
MODEL = "claude-3-5-sonnet-20240620"  # Using Claude 3.5 Sonnet for a good balance of capability/cost

# Mock job board API for MVP (would be replaced with actual API integration)
def search_jobs(query, location, limit=5):
    """Mock function to simulate job search API"""
    # In a production app, this would integrate with Indeed, LinkedIn, etc.
    sample_jobs = [
        {
            "title": "HVAC Technician Apprentice",
            "company": "Cool Air Services",
            "location": "Harrisburg, PA",
            "description": "Entry-level position learning HVAC installation and repair. No experience required, training provided.",
            "requirements": "High school diploma or GED, driver's license, basic technical aptitude",
            "url": "https://example.com/job1",
            "remote": False
        },
        {
            "title": "Remote Customer Support Specialist",
            "company": "TechHelp Solutions",
            "location": "Remote (US-based)",
            "description": "Provide technical support to customers via phone and chat. Flexible hours available.",
            "requirements": "Strong communication skills, basic computer knowledge, reliable internet",
            "url": "https://example.com/job2",
            "remote": True
        },
        {
            "title": "Electronics Repair Technician",
            "company": "FixIt Electronics",
            "location": "Allentown, PA",
            "description": "Diagnose and repair consumer electronics. Training provided for promising candidates.",
            "requirements": "Technical aptitude, problem-solving skills, customer service experience",
            "url": "https://example.com/job3",
            "remote": False
        },
        {
            "title": "Home Health Aide - Flexible Schedule",
            "company": "Caring Connections Health",
            "location": "Allentown, PA",
            "description": "Provide in-home care for elderly clients. Choose your own hours and clients.",
            "requirements": "Compassion, reliability, basic healthcare knowledge",
            "url": "https://example.com/job4",
            "remote": False
        },
        {
            "title": "Virtual Administrative Assistant",
            "company": "Remote Office Solutions",
            "location": "Remote",
            "description": "Provide administrative support to small businesses. Set your own hours.",
            "requirements": "Organization skills, communication skills, basic computer proficiency",
            "url": "https://example.com/job5",
            "remote": True
        }
    ]
    
    filtered_jobs = []
    for job in sample_jobs:
        if (query.lower() in job["title"].lower() or 
            query.lower() in job["description"].lower() or 
            not query):  # If no query, include all
            if not location or location.lower() in job["location"].lower():
                filtered_jobs.append(job)
    
    return filtered_jobs[:limit]

# Chat History Management
def format_chat_history(history):
    """Format chat history from Gradio's tuple format to Claude API format"""
    formatted_history = []
    for msg in history:
        # Gradio's chatbot format is a list of [user_message, assistant_message] pairs
        if msg[0] is not None:  # User message
            formatted_history.append({"role": "user", "content": msg[0]})
        if msg[1] is not None:  # Assistant message
            formatted_history.append({"role": "assistant", "content": msg[1]})
    return formatted_history

def get_system_prompt(module):
    """Create appropriate system prompt based on the current module"""
    base_prompt = """You are Career Compass, an AI career advisor designed to help users discover career paths, 
    develop skills, and find job opportunities. Be supportive, encouraging, and practical.
    Focus on breaking down complex career goals into achievable steps.
    Always consider the user might have limited education or face barriers to employment.
    Be concise but warm in your responses."""
    
    module_prompts = {
        "skill_mapping": base_prompt + """
        In this module, help the user identify their existing skills, including soft skills and informal experience.
        Ask about their work history, education, hobbies, and life experiences.
        Translate their experiences into recognized transferable skills employers value.
        Be sure to recognize skills from caregiving, informal work, and self-taught abilities.
        End with a concise list of their top 3-5 strengths and 2-3 areas for development.
        """,
        
        "goal_setting": base_prompt + """
        In this module, help the user set SMART career goals (Specific, Measurable, Achievable, Relevant, Time-bound).
        Focus on building their confidence and self-efficacy.
        Break larger goals into small, achievable steps.
        Provide encouragement and address potential obstacles.
        Emphasize progress over perfection and help them visualize success.
        """,
        
        "job_matching": base_prompt + """
        In this module, help the user identify suitable job opportunities based on their skills and goals.
        Consider their constraints (location, schedule, education level).
        Discuss job titles they might not have considered but match their abilities.
        Explain why specific jobs might be a good match.
        Provide practical advice on job applications and interviews for these roles.
        """
    }
    
    return module_prompts.get(module, base_prompt)

# Claude Integration Functions
def get_claude_response(messages, system_prompt, temperature=0.7):
    """Get a response from Claude based on conversation history"""
    try:
        response = client.messages.create(
            model=MODEL,
            system=system_prompt,
            messages=messages,
            temperature=temperature,
            max_tokens=1000
        )
        return response.content[0].text
    except Exception as e:
        return f"Sorry, I'm having trouble connecting right now. Error: {str(e)}"

# Main application functions for each module
def skill_mapping_chat(message, history):
    """Handle the skill mapping conversation"""
    history = history or []
    formatted_history = format_chat_history(history)
    
    # Get Claude's response
    system_prompt = get_system_prompt("skill_mapping")
    response = get_claude_response(formatted_history + [{"role": "user", "content": message}], system_prompt)
    
    # Update history and return
    history.append([message, response])
    return history

def goal_setting_chat(message, history):
    """Handle the goal setting conversation"""
    history = history or []
    formatted_history = format_chat_history(history)
    
    # Get Claude's response
    system_prompt = get_system_prompt("goal_setting")
    response = get_claude_response(formatted_history + [{"role": "user", "content": message}], system_prompt)
    
    # Update history and return
    history.append([message, response])
    return history

def job_matching_chat(message, history, job_search_results=None):
    """Handle the job matching conversation"""
    history = history or []
    formatted_history = format_chat_history(history)
    
    # If job search results exist, include them in the prompt
    user_message = message
    if job_search_results:
        job_info = "\n\nRecent job search results:\n" + json.dumps(job_search_results, indent=2)
        user_message += job_info
    
    # Get Claude's response
    system_prompt = get_system_prompt("job_matching")
    response = get_claude_response(formatted_history + [{"role": "user", "content": user_message}], system_prompt)
    
    # Update history and return
    history.append([message, response])
    return history

def job_search(query, location, history):
    """Search for jobs and integrate results into the conversation"""
    # Get job search results
    jobs = search_jobs(query, location)
    
    # Format job results for the user
    job_results_text = "Here are some job opportunities based on your search:\n\n"
    for i, job in enumerate(jobs, 1):
        job_results_text += f"**{i}. {job['title']} - {job['company']}**\n"
        job_results_text += f"**Location:** {job['location']}\n"
        job_results_text += f"**Description:** {job['description']}\n"
        job_results_text += f"**Requirements:** {job['requirements']}\n"
        job_results_text += f"**Remote:** {'Yes' if job['remote'] else 'No'}\n\n"
    
    if not jobs:
        job_results_text = "No jobs found matching your criteria. Try broadening your search terms."
    
    # Update conversation with job results
    updated_history = job_matching_chat("Show me jobs related to: " + query + 
                                         (" in " + location if location else ""), 
                                        history, jobs)
    
    return updated_history

# Initialize welcome messages for each module
WELCOME_MESSAGES = {
    "skill_mapping": """👋 Welcome to Skill Mapping! I'll help you identify your skills and strengths.

Let's start by exploring your experiences. Tell me about:
- Work you've done (paid or unpaid)
- Projects you've completed
- Problems you've solved
- Responsibilities you've handled
- Skills you've taught yourself

Don't worry if they seem informal - many skills are valuable!""",

    "goal_setting": """👋 Welcome to Goal Setting! I'll help you create achievable career goals and build confidence.

Let's start by exploring:
- What kind of work interests you?
- What's important to you in a job? (Schedule, pay, location, etc.)
- What obstacles have you faced in reaching your career goals?
- What small step could you take this week toward your career?""",

    "job_matching": """👋 Welcome to Job Matching! I'll help you find opportunities that match your skills and goals.

You can:
1. Search for jobs using the search box above
2. Ask me questions about specific careers
3. Get advice on applying for jobs

What type of work are you interested in exploring?"""
}

# UI Building
def build_ui():
    """Create the Gradio interface"""
    with gr.Blocks(theme=gr.themes.Soft(), title="Career Compass") as app:
        gr.Markdown("# Career Compass 🧭")
        gr.Markdown("Your AI-powered career development assistant")
        
        with gr.Tabs() as tabs:
            # Skill Mapping Tab
            with gr.Tab("✨ Skill Mapping"):
                gr.Markdown("Discover your strengths and transferable skills")
                with gr.Column():
                    skill_chat = gr.Chatbot(
                        value=[[None, WELCOME_MESSAGES["skill_mapping"]]],
                        height=400,
                        show_label=False,
                        type="tuples"  # Use "tuples" instead of "list"
                    )
                    skill_msg = gr.Textbox(
                        placeholder="Tell me about your experiences and interests...",
                        show_label=False
                    )
                    skill_clear = gr.Button("Clear Chat")
                
                skill_msg.submit(skill_mapping_chat, [skill_msg, skill_chat], [skill_chat]).then(
                    lambda: "", None, skill_msg)
                skill_clear.click(lambda: [[None, WELCOME_MESSAGES["skill_mapping"]]], None, skill_chat)
            
            # Goal Setting Tab
            with gr.Tab("🎯 Goal Setting"):
                gr.Markdown("Set achievable career goals and build confidence")
                with gr.Column():
                    goal_chat = gr.Chatbot(
                        value=[[None, WELCOME_MESSAGES["goal_setting"]]],
                        height=400,
                        show_label=False,
                        type="tuples"  # Use "tuples" instead of "list"
                    )
                    goal_msg = gr.Textbox(
                        placeholder="Share your career aspirations and concerns...",
                        show_label=False
                    )
                    goal_clear = gr.Button("Clear Chat")
                
                goal_msg.submit(goal_setting_chat, [goal_msg, goal_chat], [goal_chat]).then(
                    lambda: "", None, goal_msg)
                goal_clear.click(lambda: [[None, WELCOME_MESSAGES["goal_setting"]]], None, goal_chat)
            
            # Job Matching Tab
            with gr.Tab("💼 Job Matching"):
                gr.Markdown("Find job opportunities that match your skills and goals")
                with gr.Row():
                    job_query = gr.Textbox(placeholder="Job title, skills, or keywords", label="Search")
                    job_location = gr.Textbox(placeholder="City, state, or 'remote'", label="Location (optional)")
                    job_search_btn = gr.Button("Search Jobs")
                
                with gr.Column():
                    job_chat = gr.Chatbot(
                        value=[[None, WELCOME_MESSAGES["job_matching"]]],
                        height=400,
                        show_label=False,
                        type="tuples"  # Use "tuples" instead of "list" 
                    )
                    job_msg = gr.Textbox(
                        placeholder="Ask about specific careers or job search advice...",
                        show_label=False
                    )
                    job_clear = gr.Button("Clear Chat")
                
                job_msg.submit(job_matching_chat, [job_msg, job_chat], [job_chat]).then(
                    lambda: "", None, job_msg)
                job_search_btn.click(job_search, [job_query, job_location, job_chat], [job_chat])
                job_clear.click(lambda: [[None, WELCOME_MESSAGES["job_matching"]]], None, job_chat)
        
        # About section
        with gr.Accordion("About Career Compass", open=False):
            gr.Markdown("""
            ## Career Compass
            
            Career Compass helps you navigate your career journey through:
            
            * **Skill Mapping** - Discover your strengths and transferable skills
            * **Goal Setting** - Build confidence and create achievable career goals
            * **Job Matching** - Find opportunities that fit your unique abilities
            
            This tool is designed to be supportive and practical, meeting you where you are in your career journey.
            """)
    
    return app

# Main application
def main():
    app = build_ui()
    app.launch()

if __name__ == "__main__":
    main()