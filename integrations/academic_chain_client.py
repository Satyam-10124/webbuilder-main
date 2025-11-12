"""
AcademicChain API Client
Interacts with the smart contract generation and deployment backend
"""
import httpx
import asyncio
from typing import Dict, Any, Optional, List
import json


class AcademicChainClient:
    """Client for interacting with AcademicChain smart contract backend"""
    
    def __init__(self, base_url: str = "https://evi-v4-production.up.railway.app"):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=300.0)  # 5 min timeout for long operations
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()
    
    # ==================== AI Generation ====================
    
    async def generate_contract(self, prompt: str, model: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate Solidity code from natural language prompt
        
        Args:
            prompt: Natural language description of contract
            model: Optional model override
            
        Returns:
            {
                "ok": bool,
                "text": str,
                "codeBlock": {"language": str, "code": str}
            }
        """
        response = await self.client.post(
            f"{self.base_url}/api/ai/generate",
            json={"prompt": prompt, "model": model}
        )
        response.raise_for_status()
        return response.json()
    
    async def compile_contract(self, filename: str, code: str) -> Dict[str, Any]:
        """
        Compile Solidity code
        
        Args:
            filename: Name of the Solidity file
            code: Solidity source code
            
        Returns:
            Compilation result with errors if any
        """
        response = await self.client.post(
            f"{self.base_url}/api/ai/compile",
            json={"filename": filename, "code": code}
        )
        response.raise_for_status()
        return response.json()
    
    async def fix_contract(
        self,
        code: str,
        errors: str,
        network: str = "basecamp-testnet",
        context: Optional[str] = None,
        max_iters: int = 3
    ) -> Dict[str, Any]:
        """
        Fix Solidity code via AI and deploy
        
        Args:
            code: Solidity source code
            errors: Compilation errors
            network: Target network
            context: Additional context
            max_iters: Maximum fix iterations
            
        Returns:
            {
                "ok": bool,
                "job": {"id": str, "type": str}
            }
        """
        response = await self.client.post(
            f"{self.base_url}/api/ai/fix",
            json={
                "code": code,
                "errors": errors,
                "network": network,
                "context": context,
                "maxIters": max_iters
            }
        )
        response.raise_for_status()
        return response.json()
    
    async def create_dapp_pipeline(
        self,
        prompt: str,
        network: str = "basecamp-testnet",
        max_iters: int = 3,
        constructor_args: Optional[List[str]] = None,
        contract_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        End-to-end pipeline: generate, fix, compile, and deploy contract
        
        Args:
            prompt: Natural language description
            network: Target blockchain network
            max_iters: Maximum fix iterations
            constructor_args: Constructor arguments
            contract_name: Specific contract name
            
        Returns:
            {
                "ok": bool,
                "job": {"id": str, "type": str, "payload": dict}
            }
        """
        payload = {
            "prompt": prompt,
            "network": network,
            "maxIters": max_iters
        }
        
        if constructor_args:
            payload["constructorArgs"] = constructor_args
        if contract_name:
            payload["contractName"] = contract_name
            
        response = await self.client.post(
            f"{self.base_url}/api/ai/pipeline",
            json=payload
        )
        response.raise_for_status()
        return response.json()
    
    # ==================== Job Management ====================
    
    async def get_job_status(self, job_id: str, verbose: bool = False) -> Dict[str, Any]:
        """
        Get job status
        
        Args:
            job_id: Job identifier
            verbose: Include full job details and logs
            
        Returns:
            {
                "ok": bool,
                "status": str,  # 'pending', 'running', 'completed', 'failed'
                "job": dict (if verbose)
            }
        """
        params = {"verbose": "1" if verbose else "0"}
        response = await self.client.get(
            f"{self.base_url}/api/job/{job_id}/status",
            params=params
        )
        response.raise_for_status()
        return response.json()
    
    async def get_job_logs(
        self,
        job_id: str,
        level: Optional[str] = None,
        limit: int = 500
    ) -> Dict[str, Any]:
        """
        Get job logs
        
        Args:
            job_id: Job identifier
            level: Filter by level (info,warn,error,debug)
            limit: Maximum logs to return
            
        Returns:
            {"ok": bool, "logs": [...]}
        """
        params = {"limit": limit}
        if level:
            params["level"] = level
            
        response = await self.client.get(
            f"{self.base_url}/api/job/{job_id}/logs",
            params=params
        )
        response.raise_for_status()
        return response.json()
    
    async def wait_for_job_completion(
        self,
        job_id: str,
        poll_interval: float = 2.0,
        timeout: float = 300.0
    ) -> Dict[str, Any]:
        """
        Poll job until completion or timeout
        
        Args:
            job_id: Job identifier
            poll_interval: Seconds between polls
            timeout: Maximum wait time
            
        Returns:
            Final job status
        """
        start_time = asyncio.get_event_loop().time()
        
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")
            
            status = await self.get_job_status(job_id, verbose=True)
            
            job_status = status.get("status", "pending")
            if job_status in ["completed", "failed"]:
                return status
            
            await asyncio.sleep(poll_interval)
    
    # ==================== Artifacts ====================
    
    async def get_artifacts(
        self,
        job_id: str,
        include: str = "all"
    ) -> Dict[str, Any]:
        """
        Get job artifacts (sources, ABIs, scripts)
        
        Args:
            job_id: Job identifier
            include: 'all', 'sources', 'abis', or 'scripts'
            
        Returns:
            {
                "ok": bool,
                "sources": {...},
                "abis": {...},
                "scripts": {...}
            }
        """
        response = await self.client.get(
            f"{self.base_url}/api/artifacts",
            headers={"x-job-id": job_id},
            params={"include": include}
        )
        response.raise_for_status()
        return response.json()
    
    async def get_contract_abi(self, job_id: str) -> Dict[str, Any]:
        """
        Get compiled contract ABI
        
        Args:
            job_id: Job identifier
            
        Returns:
            {"ok": bool, "abis": {"ContractName": [...]}}
        """
        response = await self.client.get(
            f"{self.base_url}/api/artifacts/abis",
            headers={"x-job-id": job_id}
        )
        response.raise_for_status()
        return response.json()
    
    async def get_contract_source(self, job_id: str) -> Dict[str, Any]:
        """
        Get contract source code
        
        Args:
            job_id: Job identifier
            
        Returns:
            {"ok": bool, "sources": {"FileName.sol": "code..."}}
        """
        response = await self.client.get(
            f"{self.base_url}/api/artifacts/sources",
            headers={"x-job-id": job_id}
        )
        response.raise_for_status()
        return response.json()
    
    # ==================== Audit & Compliance ====================
    
    async def audit_contract(
        self,
        code: str,
        filename: str = "Contract.sol",
        model: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run security audit on contract
        
        Args:
            code: Solidity source code
            filename: File name
            model: Optional model override
            
        Returns:
            Audit report with vulnerabilities
        """
        response = await self.client.post(
            f"{self.base_url}/api/audit/analyze",
            json={"code": code, "filename": filename, "model": model}
        )
        response.raise_for_status()
        return response.json()
    
    async def check_compliance(
        self,
        code: str,
        profile: str = "generic",
        filename: str = "Contract.sol"
    ) -> Dict[str, Any]:
        """
        Check contract compliance (ERC standards, etc.)
        
        Args:
            code: Solidity source code
            profile: 'generic', 'registry', 'token', or 'custom'
            filename: File name
            
        Returns:
            Compliance report
        """
        response = await self.client.post(
            f"{self.base_url}/api/compliance/analyze",
            json={"code": code, "profile": profile, "filename": filename}
        )
        response.raise_for_status()
        return response.json()
    
    # ==================== Verification ====================
    
    async def verify_contract(
        self,
        address: str,
        network: str,
        fully_qualified_name: Optional[str] = None,
        constructor_args: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Verify deployed contract on block explorer
        
        Args:
            address: Contract address
            network: Network name
            fully_qualified_name: e.g., "contracts/File.sol:Contract"
            constructor_args: Constructor arguments
            
        Returns:
            Verification result
        """
        payload = {
            "address": address,
            "network": network
        }
        
        if fully_qualified_name:
            payload["fullyQualifiedName"] = fully_qualified_name
        if constructor_args:
            payload["args"] = constructor_args
            
        response = await self.client.post(
            f"{self.base_url}/api/verify/byAddress",
            json=payload
        )
        response.raise_for_status()
        return response.json()
    
    async def verify_by_job(
        self,
        job_id: str,
        network: str,
        fully_qualified_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Verify contract using artifacts from a job
        
        Args:
            job_id: Job identifier
            network: Network name
            fully_qualified_name: Optional contract name
            
        Returns:
            Verification result
        """
        payload = {
            "jobId": job_id,
            "network": network
        }
        
        if fully_qualified_name:
            payload["fullyQualifiedName"] = fully_qualified_name
            
        response = await self.client.post(
            f"{self.base_url}/api/verify/byJob",
            json=payload
        )
        response.raise_for_status()
        return response.json()


# Network configuration helpers
NETWORK_CONFIG = {
    "basecamp-testnet": {
        "chain_id": 84532,
        "name": "Base Camp Testnet",
        "rpc": "https://sepolia.base.org",
        "explorer": "https://sepolia.basescan.org"
    },
    "sepolia": {
        "chain_id": 11155111,
        "name": "Ethereum Sepolia",
        "rpc": "https://ethereum-sepolia-rpc.publicnode.com",
        "explorer": "https://sepolia.etherscan.io"
    },
    "polygon": {
        "chain_id": 137,
        "name": "Polygon",
        "rpc": "https://polygon.llamarpc.com",
        "explorer": "https://polygonscan.com"
    },
    "avalanche-fuji": {
        "chain_id": 43113,
        "name": "Avalanche Fuji",
        "rpc": "https://api.avax-test.network/ext/bc/C/rpc",
        "explorer": "https://testnet.snowtrace.io"
    }
}


def get_network_info(network: str) -> Dict[str, Any]:
    """Get network configuration by name"""
    return NETWORK_CONFIG.get(network, {})


def get_explorer_url(network: str, address: str) -> str:
    """Generate block explorer URL for contract"""
    config = get_network_info(network)
    if not config:
        return ""
    return f"{config['explorer']}/address/{address}"
