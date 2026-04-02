"""Gradio interface for outreach campaign execution with streaming progress."""

import gradio as gr
import asyncio
import logging
from typing import Iterator, Tuple
from outreach.marketing_agent import senior_marketing_agent

logger = logging.getLogger(__name__)


async def execute_campaign_with_progress() -> Iterator[Tuple[str, str]]:
    """Execute campaign with streaming progress updates.
    
    The campaign details are automatically retrieved from database via get_campaign_tool.
        
    Yields:
        Tuple of (progress_message, status)
    """
    try:
        yield ("🚀 Initializing campaign execution...", "info")
        await asyncio.sleep(0.5)  # Small delay for UI
        
        yield ("📊 Calling get_campaign_tool: Retrieving campaign from database...", "info") 
        await asyncio.sleep(0.5)
        
        yield ("👤 Calling get_lead_tool: Fetching eligible lead...", "info")
        await asyncio.sleep(0.5)
        
        yield ("✍️ Calling content tools: Generating 3 email variations...", "info")
        await asyncio.sleep(1)
        
        yield ("🧠 Agent evaluation: Selecting best email draft...", "info") 
        await asyncio.sleep(0.5)
        
        yield ("📤 Calling send_agent_email: Delivering email...", "info")
        
        # Execute the actual campaign (no campaign_brief needed - comes from database)
        result = await senior_marketing_agent.execute_campaign()
        
        if result.get("success"):
            yield (f"✅ Campaign completed successfully!\\n{result.get('message', '')}", "success")
        else:
            yield (f"❌ Campaign failed: {result.get('error', 'Unknown error')}", "error")
            
    except Exception as e:
        logger.error(f"Campaign execution error: {e}")
        yield (f"❌ Execution failed: {str(e)}", "error")


def execute_campaign_sync() -> Iterator[str]:
    """Synchronous wrapper for campaign execution with progress."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        async_gen = execute_campaign_with_progress()
        while True:
            try:
                progress_msg, status = loop.run_until_complete(async_gen.__anext__())
                
                # Format message with emoji based on status
                if status == "success":
                    yield f"🎉 {progress_msg}"
                elif status == "error":
                    yield f"🚨 {progress_msg}"
                else:
                    yield f"⏳ {progress_msg}"
                    
            except StopAsyncIteration:
                break
    finally:
        loop.close()


def create_outreach_interface():
    """Create the Gradio interface for outreach campaigns."""
    
    with gr.Blocks(title="📧 Agent-Driven Outreach Platform") as interface:
        
        gr.Markdown("# 📧 Senior Marketing Agent - Outreach Campaigns")
        gr.Markdown("Execute intelligent outreach campaignscontent generation and evaluation.")
        
        with gr.Row():
            with gr.Column(scale=2):
                gr.Markdown("### 🎯 Automated Campaign Execution")
                gr.Markdown("Click below to start an automated outreach campaign. The system will:")
                gr.Markdown("- Select a campaign from database\n- Find an eligible lead\n- Generate 3 email styles\n- Choose the best one\n- Send the email")
                
                execute_btn = gr.Button(
                    "🚀 Start Campaign", 
                    variant="primary",
                    size="lg"
                )
                
            with gr.Column(scale=3):
                progress_output = gr.Textbox(
                    label="Campaign Progress & Results",
                    lines=12,
                    max_lines=15,
                    interactive=False
                )
        
        # Status indicators
        with gr.Row():
            gr.Markdown("### 📊 Campaign Workflow")
            gr.Markdown("""
            1. Retrieve random campaign from database
            2. Find eligible lead for outreach  
            3. Content Generation
            4. AI Evaluation
            5. Deliver personalized email to lead
            """)
        
        # Event handlers
        execute_btn.click(
            fn=execute_campaign_sync,
            inputs=[],
            outputs=[progress_output],
            show_progress=True
        )
        
        # Info section
        with gr.Row():
            gr.Markdown("### ℹ️ How it works")
            gr.Markdown("The system automatically selects campaigns and leads from the database, generates personalized content, and sends emails without manual input.")
    
    return interface


# Interface is created when imported into FastAPI application