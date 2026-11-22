# Weekly Cyber Incident Summary (Nov 10-17, 2026)

The feed logged **36 entries**: 4 rated "dominion", 26 "siege" and 6 "breach". These are the feed's own severity labels. Several events were reported by more than one outlet (Optimizely three times, and Uber, Cursor and Trezor twice each), so there are roughly **31 distinct incidents**.

## Key takeaways
- **Supply-chain attacks dominated.** Optimizely, Fireworks AI, ConnectWise, N-able and Hugging Face were all entry points to downstream victims.
- **Third-party vendors were the weak link.** One compromised provider exposed many customers.
- **AI showed up on both sides.** Attackers used agentic pentesting tools (ARTEX, AntiFox) and AI agents for credential theft, and AI platforms themselves were targeted.
- **State-backed actors** were behind the largest financial losses.

## Biggest incidents

**Optimizely hijack (dominion).** Attackers injected malicious JavaScript through Optimizely Web Experimentation into at least 178 customer sites, including CNN, BBC, Fox News, Zoom, Salesforce and GitLab. Visitors were exposed to a card and crypto skimmer and an iOS exploit kit. Recommended defenses: Subresource Integrity (SRI) and a strict CSP.

**North Korean operations (dominion).**
- The FBI said DPRK operators stole over $400M in crypto using deepfake video calls impersonating executives.
- A separate report described fake job interviews with malicious coding tasks that enabled a $6.3B crypto heist.

## Supply chain and third-party compromises
- **Fireworks AI → Cursor and Uber.** A stolen key led to a trojanized Claude Code extension on Cursor's marketplace. The same breach exposed data of nearly 150,000 Uber drivers.
- **ConnectWise ScreenConnect.** CVE-2026-84869 (CVSS 9.9) was exploited with the SCKit toolkit to reach MSPs. Rogue clients hit 288+ endpoints across 48 organizations. The FBI also warned that the AI pentest framework ARTEX was used against ConnectWise to reach Microsoft 365 tenants.
- **N-able N-central.** The flaws 4EverAble2Shell and Agent2Shell compromised 21 servers, 19 of them already on Hotfix 2.
- **GitHub.** 4,837 hijacked accounts ran a CI secret stealer in 1,806+ repositories.
- **Trezor.** Wallets sold by the reseller CryptoBilis contained implants that steal recovery phrases. Trezor confirmed the tampering and released a fix.
- **Hugging Face.** Researchers hijacked the account for the Kokoro TTS model, which is used by Google, NVIDIA, AMD, Intel and AWS. A poisoned model could have been pushed downstream.
- **eMudhra (India).** A flawed in-house script caused a key compromise, forcing the CA to revoke 8 more intermediate CAs it had previously declared unaffected.

## Actively exploited vulnerabilities and targeted attacks
- **UnrealIRCd:** CVE-2026-114713 (command injection, CVSS 8.6), added to CISA KEV.
- **Check Point gateways:** PHP2Shell flaws plus a Gaia OS privilege escalation were used to deploy the TSGA backdoor and wipe ESXi files at Israeli organizations.
- **BO Team:** exploited Log4Shell in VMware vCenter to compromise a Russian firm's code-signing server.
- **AntiFox:** an agentic AI pentesting platform was linked to attacks that stole AWS production secrets and enabled lateral movement.
- **Fugaku:** Japan took the Fugaku supercomputer offline after a cyberattack.

## Espionage and state-linked activity
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

## Law enforcement
- **Operation Endgame:** took down Gootloader, CastleRAT and StealC infrastructure and recovered 6.4M stolen logins.
- **Rockstar/GTA 6:** Arion Kurtaj (Lapsus$) pleaded guilty to the hack.

## Common defensive themes
1. Use phishing-resistant MFA (FIDO2) instead of SMS.
2. Use short-lived, scoped credentials and OIDC for CI/CD.
3. Apply SRI and CSP to third-party scripts.
4. Vet, minimize and segment third-party vendor access.
5. Enforce least-privilege IAM with anomaly alerting in cloud environments.
6. Patch KEV-listed and actively exploited flaws immediately.
