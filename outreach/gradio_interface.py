"""Gradio interface for outreach campaign execution with streaming progress."""

import gradio as gr
import asyncio
import logging
from typing import Iterator, Tuple, List
from outreach.marketing_agent import senior_marketing_agent
from tools.campaign_tools import get_active_campaigns

logger = logging.getLogger(__name__)


async def execute_campaign_with_progress(campaign_name: str = None) -> Iterator[Tuple[str, str]]:
    """Execute campaign with streaming progress updates.
    
    The campaign details are automatically retrieved from database via get_campaign_tool.
        
    Args:
        campaign_name: Optional name of the specific campaign to run.
        
    Yields:
        Tuple of (progress_message, status)
    """
    try:
        yield ("🚀 Initializing campaign execution...", "info")
        await asyncio.sleep(0.5)  # Small delay for UI
        
        target = f" campaign '{campaign_name}'" if campaign_name else " a random campaign"
        yield (f"📊 Calling get_campaign_tool: Retrieving{target} from database...", "info") 
        await asyncio.sleep(0.5)
        
        yield ("👤 Calling get_lead_tool: Fetching eligible lead...", "info")
        await asyncio.sleep(0.5)
        
        yield ("✍️ Calling content tools: Generating 3 email variations...", "info")
        await asyncio.sleep(1)
        
        yield ("🧠 Agent evaluation: Selecting best email draft...", "info") 
        await asyncio.sleep(0.5)
        
        yield ("📤 Calling send_agent_email: Delivering email...", "info")
        
        # Execute the actual campaign (no campaign_brief needed - comes from database)
        result = await senior_marketing_agent.execute_campaign(campaign_name=campaign_name)
        
        if result.get("success"):
            yield (f"✅ Campaign completed successfully!\n{result.get('message', '')}", "success")
        else:
            yield (f"❌ Campaign failed: {result.get('error', 'Unknown error')}", "error")
            
    except Exception as e:
        logger.error(f"Campaign execution error: {e}")
        yield (f"❌ Execution failed: {str(e)}", "error")


def execute_campaign_sync(campaign_name: str) -> Iterator[str]:
    """Synchronous wrapper for campaign execution with progress."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        async_gen = execute_campaign_with_progress(campaign_name=campaign_name)
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


def get_campaign_names() -> List[str]:
    """Get names of all active campaigns for the dropdown."""
    campaigns = get_active_campaigns()
    return [c.name for c in campaigns]


def create_outreach_interface():
    """Create the Gradio interface for outreach campaigns."""
    
    with gr.Blocks(title="📧 Agent-Driven Outreach Platform") as interface:
        
        gr.Markdown("# 📧 Senior Marketing Agent - Outreach Campaigns")
        gr.Markdown("Execute intelligent outreach campaigns with multi-style content generation and AI evaluation.")
        
        with gr.Row():
            with gr.Column(scale=2):
                gr.Markdown("### 🎯 Automated Campaign Execution")
                
                # Dropdown for campaign selection
                campaign_dropdown = gr.Dropdown(
                    choices=get_campaign_names(),
                    label="Select Campaign",
                    info="Choose an active campaign to run. If none are listed, ensure campaigns are set to ACTIVE in the database.",
                    value=get_campaign_names()[0] if get_campaign_names() else None
                )
                
                gr.Markdown("Click below to start the selected outreach campaign. The system will:")
                gr.Markdown("- Retrieve details for the selected campaign\n- Find an eligible lead\n- Generate 3 email styles\n- Choose the best one\n- Send the email")
                
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
        
        # Event handlers
        execute_btn.click(
            fn=execute_campaign_sync,
            inputs=[campaign_dropdown],
            outputs=[progress_output],
            show_progress=True
        )
        
        # Info section
        with gr.Row():
            gr.Markdown("### ℹ️ How it works")
            gr.Markdown("The system automatically selects campaigns and leads from the database, generates personalized content, and sends emails without manual input.")
    
    return interface


# Interface is created when imported into FastAPI application