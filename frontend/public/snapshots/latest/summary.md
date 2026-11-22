# Weekly Cyber Incident Summary (Nov 12-19, 2026)

The feed logged **44 incidents** this week: 6 rated "dominion", 33 "siege" and 5 "breach". These are the feed's own severity labels.

## Key takeaways
- **Supply-chain attacks dominated.** Optimizely, Fireworks AI, Microsoft's PyPI package, ConnectWise and N-able all served as entry points to downstream victims.
- **Third-party vendors were the weak link.** A single compromised provider cascaded into many customers.
- **Several critical flaws were exploited in the wild**, including two CISA KEV additions.
- **State-backed actors** were behind the largest financial losses and a series of espionage campaigns.

## Biggest incidents

**Optimizely hijack (dominion).** Attackers injected malicious JavaScript through the Optimizely Web Experimentation platform into at least 178 customer sites, including CNN, BBC, Fox News, Zoom, Salesforce and GitLab. Visitors were exposed to a card and crypto skimmer and an iOS exploit kit. Recommended defense: Subresource Integrity (SRI) and a strict CSP.

**North Korean operations (dominion).** The FBI said DPRK operators stole over $400M in crypto using deepfake video calls impersonating executives. A separate report described fake job interviews with malicious coding tasks that enabled a $6.3B crypto heist.

## Supply chain and third-party compromises
- **Fireworks AI → Cursor and Uber.** A stolen key led to a trojanized Claude Code extension on Cursor's marketplace. The same Fireworks AI breach exposed data of nearly 150,000 Uber drivers.
- **Microsoft agent-framework (PyPI).** Malicious versions 1.26.1 and 1.26.2 were published within 33 minutes of each other and steal cloud credentials whenever Python starts.
- **ConnectWise ScreenConnect.** CVE-2026-84869 (CVSS 9.9) was exploited with the SCKit toolkit. Separately, rogue clients hit 288+ endpoints across 48 organizations. The FBI also warned that the AI pentest framework ARTEX was used against ConnectWise to reach Microsoft 365 tenants.
- **N-able.** The N-central flaws (4EverAble2Shell and Agent2Shell) compromised 21 servers, 19 of them already on Hotfix 2. Hackers also breached the Mail Assure and Spam Experts cloud, disrupting service in three regions.
- **Wellington IT.** The IT provider was hacked, exposing member data from roughly 50 credit unions, mostly in Ireland.
- **GitHub.** 4,837 hijacked accounts ran a CI secret stealer in 1,806+ repositories.
- **Trezor.** Wallets sold by the reseller CryptoBilis contained implants that steal recovery phrases. Trezor confirmed the tampering and released a fix.
- **Hugging Face.** Researchers hijacked the account for the Kokoro TTS model, which is used by Google, NVIDIA, AMD, Intel and AWS. It showed that a poisoned model could have been pushed downstream.

## Actively exploited vulnerabilities
- **Perforce Puppet:** CVE-2026-115731 (RCE, CVSS 9.4), added to CISA KEV.
- **UnrealIRCd:** CVE-2026-114713 (command injection, CVSS 8.6), added to CISA KEV.
- **Apache Roller:** RCE exploited in attacks; patches are available.
- **Check Point gateways:** PHP2Shell flaws plus a Gaia OS privilege escalation were used to deploy the TSGA backdoor and wipe ESXi files at Israeli organizations.
- **BO Team:** exploited Log4Shell in VMware vCenter to compromise a Russian firm's code-signing server.
- **Fugaku:** Japan took the Fugaku supercomputer offline after a cyberattack.

## Espionage and state-linked activity
- **COLD RELIC (Russia):** used stolen Google Workspace data to breach a second U.S. organization.
- **EggStreme (suspected China):** retooled malware targeting Philippine government bodies.
- **Operation ShadowCloud:** GitDoor and GraphDoor backdoors abuse GitHub and SharePoint as C2 against governments in Asia and Africa.
- **SilentAir:** hijacked telecom networks to intercept SMS 2FA codes in Taiwan.

## Phishing, credential theft and malware
- **Operation CloudFire:** calendar invites and live proxies hijacked Google session tokens.
- **TypoPrompting:** 186 fake AI-tool domains served ClickFix lures and browser hijackers.
- **AI agent campaign:** attackers used AI agents to steal API keys from LiteLLM, One API and Dify deployments.
- **SANSAR:** Linux cryptomining malware that falsifies NVIDIA GPU readings to hide mining.

## Other breaches and disruptions
- **Fandango:** a checkout-page skimmer stole payment card details.
- **TSMC:** about 6.9 GB of employee data was put up for auction, linked to a cloud provider.
- **Lithuanian Customs:** a cyberattack took its user portal offline temporarily.
- **Quantum Systems (Germany):** a cyberattack disrupted its military drone operations.
- **Tor:** an ongoing DDoS attack on relays prompted an emergency update.

## Law enforcement wins
- **Operation Endgame:** took down Gootloader, CastleRAT and StealC infrastructure and recovered 6.4M stolen logins.
- **Ukraine/FBI:** arrested four ransomware suspects tied to $40.5M in ransoms from 28+ companies.
- **Sentencing and plea:** Scattered Spider's Tyler Buchanan got six years in a U.S. prison for an $11M SIM-swap scheme. Arion Kurtaj (Lapsus$) pleaded guilty to the Rockstar/GTA 6 hack.

## Common defensive themes
1. Use phishing-resistant MFA (FIDO2) instead of SMS.
2. Use short-lived, scoped credentials and OIDC for CI/CD.
3. Pin dependencies and verify hashes.
4. Apply SRI and CSP to third-party scripts.
5. Vet and segment third-party vendor access.
6. Patch KEV-listed flaws immediately.