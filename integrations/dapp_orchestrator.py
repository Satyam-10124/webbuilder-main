"""
DApp Orchestration Service
Coordinates smart contract deployment (AcademicChain) with frontend generation (WebBuilder)
"""
import asyncio
import uuid
import json
from typing import Dict, Any, Optional
from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .academic_chain_client import AcademicChainClient, get_explorer_url
from agent.service import Service as WebBuilderService
from db.models import Chat, Contract, Message


class DAppOrchestrator:
    """
    Orchestrates full DApp creation:
    1. Generate & deploy smart contract (AcademicChain)
    2. Generate React frontend with Web3 integration (WebBuilder)
    """
    
    def __init__(self):
        self.academic_chain = AcademicChainClient()
        self.webbuilder = WebBuilderService()
    
    async def close(self):
        """Clean up resources"""
        await self.academic_chain.close()
    
    async def create_full_dapp(
        self,
        db: AsyncSession,
        chat_id: str,
        prompt: str,
        network: str = "basecamp-testnet",
        socket: Optional[WebSocket] = None,
        user_id: Optional[int] = None,
        contract_only: bool = False
    ) -> Dict[str, Any]:
        """
        End-to-end DApp creation from a single prompt
        
        Args:
            db: Database session
            chat_id: Chat/Project ID
            prompt: Natural language description of the DApp
            network: Target blockchain network
            socket: WebSocket for real-time updates
            user_id: User ID for authentication
            contract_only: If True, only deploy contract (skip frontend)
            
        Returns:
            {
                "success": bool,
                "contract_address": str,
                "contract_abi": list,
                "network": str,
                "explorer_url": str,
                "frontend_url": str (if contract_only=False),
                "job_id": str,
                "error": str (if failed)
            }
        """
        try:
            # Send initial status
            if socket:
                await self._send_status(socket, "starting", "Starting DApp creation pipeline...")
            
            # ========== PHASE 1: Smart Contract Deployment ==========
            if socket:
                await self._send_status(socket, "contract_generating", "Generating smart contract with AI...")
            
            # Start contract pipeline
            pipeline_result = await self.academic_chain.create_dapp_pipeline(
                prompt=prompt,
                network=network,
                max_iters=3
            )
            
            job_id = pipeline_result["job"]["id"]
            
            if socket:
                await self._send_status(
                    socket, 
                    "contract_deploying", 
                    f"Contract pipeline started (Job: {job_id}). Compiling and deploying..."
                )
            
            # Wait for deployment to complete
            final_status = await self.academic_chain.wait_for_job_completion(
                job_id=job_id,
                poll_interval=3.0,
                timeout=300.0
            )
            
            if final_status.get("status") != "completed":
                error_msg = "Contract deployment failed"
                if socket:
                    await self._send_status(socket, "contract_failed", error_msg)
                return {"success": False, "error": error_msg, "job_id": job_id}
            
            # Get deployment artifacts
            artifacts = await self.academic_chain.get_artifacts(job_id)
            
            # Extract contract info from job payload
            job_data = final_status.get("job", {})
            deployment_data = job_data.get("result", {})
            
            contract_address = deployment_data.get("address")
            if not contract_address:
                error_msg = "Contract address not found in deployment result"
                if socket:
                    await self._send_status(socket, "contract_failed", error_msg)
                return {"success": False, "error": error_msg, "job_id": job_id}
            
            # Get ABI
            abi_data = await self.academic_chain.get_contract_abi(job_id)
            abis = abi_data.get("abis", {})
            contract_abi = list(abis.values())[0] if abis else []
            
            # Get source code
            source_data = await self.academic_chain.get_contract_source(job_id)
            sources = source_data.get("sources", {})
            source_code = list(sources.values())[0] if sources else ""
            
            # Determine contract name
            contract_name = deployment_data.get("name", "DAppContract")
            
            # Get network info
            from .academic_chain_client import get_network_info
            network_info = get_network_info(network)
            chain_id = network_info.get("chain_id", 0)
            
            explorer_url = get_explorer_url(network, contract_address)
            
            if socket:
                await self._send_status(
                    socket,
                    "contract_deployed",
                    f"✅ Contract deployed at {contract_address}"
                )
            
            # Save contract to database
            contract = Contract(
                id=str(uuid.uuid4()),
                chat_id=chat_id,
                contract_name=contract_name,
                contract_address=contract_address,
                network=network,
                chain_id=chain_id,
                abi=contract_abi,
                source_code=source_code,
                job_id=job_id,
                deploy_tx_hash=deployment_data.get("transactionHash"),
                verified=False,
                explorer_url=explorer_url,
                deployment_status="deployed"
            )
            
            db.add(contract)
            await db.commit()
            
            # Store contract info in message history
            contract_message = Message(
                id=str(uuid.uuid4()),
                chat_id=chat_id,
                role="assistant",
                content=f"Smart contract deployed successfully!\n\nAddress: {contract_address}\nNetwork: {network}\nExplorer: {explorer_url}",
                event_type="contract_deployed"
            )
            db.add(contract_message)
            await db.commit()
            
            # If contract-only mode, return here
            if contract_only:
                return {
                    "success": True,
                    "contract_address": contract_address,
                    "contract_abi": contract_abi,
                    "network": network,
                    "chain_id": chain_id,
                    "explorer_url": explorer_url,
                    "job_id": job_id
                }
            
            # ========== PHASE 2: Frontend Generation ==========
            if socket:
                await self._send_status(
                    socket,
                    "frontend_generating",
                    "Generating React frontend with Web3 integration..."
                )
            
            # Create enhanced prompt for frontend with contract details
            frontend_prompt = self._create_frontend_prompt(
                original_prompt=prompt,
                contract_address=contract_address,
                contract_name=contract_name,
                abi=contract_abi,
                network=network,
                chain_id=chain_id
            )
            
            # Run WebBuilder agent
            # Note: This uses the existing run_agent_stream which expects WebSocket
            # The agent will automatically use the new tools (save_contract_info, create_web3_boilerplate)
            
            # We need to pass contract info to the agent through the enhanced prompt
            # The agent's prompt already instructs it to handle Web3 setup when it sees contract info
            
            if socket:
                await self._send_status(socket, "frontend_building", "Building UI components...")
            
            # Get sandbox and run agent
            sandbox = await self.webbuilder.get_e2b_sandbox(chat_id)
            
            # Run the agent workflow (this will generate the frontend)
            # The socket messages from the agent will stream to the user automatically
            await self.webbuilder.run_agent_stream(
                id=chat_id,
                prompt=frontend_prompt,
                socket=socket,
                db=db
            )
            
            # Get the app URL (should be set by the agent service)
            result = await db.execute(select(Chat).where(Chat.id == chat_id))
            chat = result.scalar_one_or_none()
            frontend_url = chat.app_url if chat else f"https://{chat_id}.e2b.dev"
            
            if socket:
                await self._send_status(
                    socket,
                    "completed",
                    f"🎉 DApp created successfully!\n\nFrontend: {frontend_url}\nContract: {contract_address}"
                )
            
            return {
                "success": True,
                "contract_address": contract_address,
                "contract_abi": contract_abi,
                "network": network,
                "chain_id": chain_id,
                "explorer_url": explorer_url,
                "frontend_url": frontend_url,
                "job_id": job_id
            }
            
        except Exception as e:
            error_msg = f"DApp creation failed: {str(e)}"
            if socket:
                await self._send_status(socket, "failed", error_msg)
            
            return {
                "success": False,
                "error": error_msg
            }
    
    async def create_frontend_for_existing_contract(
        self,
        db: AsyncSession,
        chat_id: str,
        contract_address: str,
        abi: list,
        network: str,
        prompt: str,
        socket: Optional[WebSocket] = None
    ) -> Dict[str, Any]:
        """
        Generate frontend for an already deployed contract
        
        Args:
            db: Database session
            chat_id: Project ID
            contract_address: Deployed contract address
            abi: Contract ABI
            network: Network name
            prompt: Description of desired UI
            socket: WebSocket for updates
            
        Returns:
            {"success": bool, "frontend_url": str, "error": str}
        """
        try:
            if socket:
                await self._send_status(socket, "starting", "Creating frontend for existing contract...")
            
            # Get network info
            from .academic_chain_client import get_network_info
            network_info = get_network_info(network)
            chain_id = network_info.get("chain_id", 0)
            
            # Create frontend prompt with contract details
            frontend_prompt = self._create_frontend_prompt(
                original_prompt=prompt,
                contract_address=contract_address,
                contract_name="Contract",
                abi=abi,
                network=network,
                chain_id=chain_id
            )
            
            # Save contract to database
            contract = Contract(
                id=str(uuid.uuid4()),
                chat_id=chat_id,
                contract_name="ImportedContract",
                contract_address=contract_address,
                network=network,
                chain_id=chain_id,
                abi=abi,
                source_code=None,
                job_id=None,
                verified=False,
                explorer_url=get_explorer_url(network, contract_address),
                deployment_status="imported"
            )
            
            db.add(contract)
            await db.commit()
            
            # Run WebBuilder
            sandbox = await self.webbuilder.get_e2b_sandbox(chat_id)
            
            await self.webbuilder.run_agent_stream(
                id=chat_id,
                prompt=frontend_prompt,
                socket=socket,
                db=db
            )
            
            # Get frontend URL
            result = await db.execute(select(Chat).where(Chat.id == chat_id))
            chat = result.scalar_one_or_none()
            frontend_url = chat.app_url if chat else f"https://{chat_id}.e2b.dev"
            
            return {
                "success": True,
                "frontend_url": frontend_url,
                "contract_address": contract_address
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _create_frontend_prompt(
        self,
        original_prompt: str,
        contract_address: str,
        contract_name: str,
        abi: list,
        network: str,
        chain_id: int
    ) -> str:
        """
        Create enhanced prompt for frontend generation with contract details
        """
        return f"""
Build a Web3 React frontend for the following smart contract:

CONTRACT DETAILS:
- Name: {contract_name}
- Address: {contract_address}
- Network: {network} (Chain ID: {chain_id})
- ABI: {json.dumps(abi, indent=2)}

ORIGINAL REQUEST:
{original_prompt}

REQUIREMENTS:
1. Use the create_web3_boilerplate() tool to set up wagmi and RainbowKit
2. Use the save_contract_info() tool to save the contract details
3. Build a modern, responsive UI with:
   - Wallet connection button (prominent in header)
   - Read functions displayed in cards/sections
   - Write functions with input forms and transaction feedback
   - Loading states and error handling
   - Transaction history/status
4. Use Tailwind CSS for styling
5. Add proper error messages for wallet connection, wrong network, etc.
6. For payable functions, clearly show the ETH amount required

Make the UI intuitive and user-friendly for Web3 interactions.
"""
    
    async def _send_status(self, socket: WebSocket, event: str, message: str):
        """Send status update via WebSocket"""
        try:
            await socket.send_json({
                "e": event,
                "message": message
            })
        except Exception as e:
            print(f"Failed to send WebSocket message: {e}")


# Singleton instance
dapp_orchestrator = DAppOrchestrator()
