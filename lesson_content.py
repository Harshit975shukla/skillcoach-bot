"""
Pre-written lesson content for all core topics.
Gemini/Groq is only used to generate the interview Q&A at the end.
This guarantees full, consistent lessons regardless of API availability.
"""

LESSONS = {
    "ec2": {
        "title": "AWS EC2: Instance Types, Auto Scaling & Cost Optimization",
        "why": (
            "EC2 is the foundation of almost every AWS architecture. Senior DevOps interviewers ask about it "
            "because it tests whether you understand compute trade-offs, cost management, and resilience design. "
            "Companies like Amazon, Flipkart, and Swiggy have millions in annual EC2 spend — a senior who "
            "picks the wrong instance type or misses a Reserved Instance opportunity costs real money."
        ),
        "what": (
            "Amazon EC2 (Elastic Compute Cloud) provides resizable virtual machines in the cloud, launched in 2006 "
            "as an early AWS infrastructure service. You choose CPU, memory, storage, and networking; AWS handles "
            "the underlying physical hardware. EC2 fits into the AWS ecosystem as the compute layer that runs "
            "containers, application servers, batch jobs, and anything else needing a full OS."
        ),
        "concepts": [
            {
                "name": "Instance Families and Types",
                "body": (
                    "EC2 instances are grouped by family: General Purpose (t3, m6i), Compute Optimized (c6i), "
                    "Memory Optimized (r6i, x2idn), Storage Optimized (i3, d3), and Accelerated (p4, g5 for GPU). "
                    "Available sizes and CPU-to-memory ratios vary by family; check the selected instance specification. "
                    "The t-family uses burstable performance: you earn CPU credits when idle and spend them during "
                    "spikes — ideal for dev/test but dangerous for production workloads with sustained load. "
                    "Distinguish credit modes: Standard eventually returns toward its baseline when credits run out; "
                    "Unlimited can sustain above-baseline CPU but may charge for surplus credits. T3 normally launches "
                    "in Unlimited mode, except for cases such as Dedicated Hosts. Check CPUCreditBalance and "
                    "CPUSurplusCreditsCharged before comparing burstable versus fixed-performance instance costs."
                ),
            },
            {
                "name": "Purchasing Options: On-Demand, Reserved, Spot, Savings Plans",
                "body": (
                    "On-Demand costs the most but has no commitment — good for unpredictable or short workloads. "
                    "Reserved Instances trade one- or three-year commitments for discounts, with flexibility depending "
                    "on scope, platform and RI type. Convertible RIs permit eligible exchanges. "
                    "Spot Instances use spare capacity at variable discounts but can be interrupted with a two-minute "
                    "notice — perfect for batch jobs, rendering, and stateless workers. "
                    "Savings Plans (Compute and EC2) are more flexible than RIs: you commit to $/hour spend, not "
                    "a specific instance. Real-world rule: baseline load on Reserved/Savings Plans, variable load "
                    "on On-Demand, fault-tolerant batch on Spot."
                ),
            },
            {
                "name": "Auto Scaling Groups (ASG)",
                "body": (
                    "An ASG automatically adds or removes EC2 instances based on demand, maintaining a min/max/desired "
                    "count. Scaling policies include Target Tracking (keep CPU at 60%), Step Scaling (add 2 instances "
                    "when CPU > 80%), and Scheduled Scaling (scale up at 9 AM). "
                    "Launch Templates define what instance to launch — type, AMI, security groups, user data. "
                    "Simple scaling uses cooldowns (default 300 seconds); target tracking and step scaling use "
                    "instance warmup behavior instead. Critical gotcha: ASG health checks can be EC2-level or ELB-level "
                    "(is the app responding?). Use ELB health checks in production — EC2-level passes even if your "
                    "app is crashed."
                ),
            },
            {
                "name": "Placement Groups and Networking",
                "body": (
                    "Placement Groups influence physical placement. Cluster placement packs instances close together "
                    "within one AZ, not necessarily one rack, for low latency — useful for HPC and tightly coupled apps. "
                    "Spread placement puts instances on different hardware racks — max 7 per AZ, used for critical "
                    "instances that must not fail together. Partition placement divides instances into groups of "
                    "racks — used for Hadoop, Cassandra. "
                    "Enhanced Networking uses supported adapters such as ENA; bandwidth depends on the instance type. "
                    "One thing most engineers miss: you cannot add a running instance to a Cluster placement group "
                    "without stopping and restarting it."
                ),
            },
        ],
        "e2e": [
            "1. You submit a RunInstances API call specifying AMI, instance type, subnet, security group, and key pair.",
            "2. EC2 scheduler finds physical hardware in the target AZ with enough capacity.",
            "3. EC2 allocates resources using the selected platform; modern families commonly use the Nitro System.",
            "4. The AMI (backed by an EBS snapshot) is used to create a root EBS volume.",
            "5. The instance boots and runs user data. An integrated ASG or your automation registers its target.",
            "6. Load balancer target health checks gate traffic according to the target group's configured behavior.",
            "7. If in an ASG, the ASG monitors CloudWatch metrics and scales out/in automatically.",
            "8. On termination: EBS root volume is deleted (unless configured otherwise), Elastic IP must be released manually.",
        ],
        "tasks": [
            {
                "name": "Task 1 (20 min): Launch and compare two instance types",
                "goal": "Understand real-world performance difference between t3.micro and c6i.large",
                "steps": [
                    "Launch a t3.micro and a c6i.large in the same subnet.",
                    "SSH in, run `sysbench cpu run` on both and note the difference.",
                    "Check CPU credit balance on t3.micro in CloudWatch.",
                    "Terminate both — note the cost difference in the pricing calculator.",
                ],
            },
            {
                "name": "Task 2 (15 min): Set up an Auto Scaling Group",
                "goal": "Understand how ASG integrates with ALB and health checks",
                "steps": [
                    "Create a Launch Template with a supported Amazon Linux image, a small instance, and a web server.",
                    "Create an ASG with min=1, max=3, desired=2, attached to an ALB.",
                    "Set a Target Tracking policy for CPU at 50% and observe the desired count.",
                ],
            },
            {
                "name": "Task 3 (20 min): Write out your answer to this interview question",
                "goal": "Practice structuring a complete Senior DevOps answer about cost optimization",
                "steps": [
                    "Question: 'Your EC2 bill is $50k/month. How do you reduce it by 40%?'",
                    "Write your answer covering: Savings Plans, right-sizing, Spot for batch, ASG scheduling.",
                    "Time yourself — a strong answer should take 3-4 minutes to deliver.",
                ],
            },
        ],
        "key_terms": [
            "Nitro Hypervisor — AWS's lightweight bare-metal hypervisor, replaces Xen, gives near-native performance.",
            "CPU Credits — burstable performance tokens earned at idle, spent at high CPU on t-family instances.",
            "Launch Template — versioned config (AMI, type, SG, user data) used by ASG and EC2 Fleet.",
            "Target Tracking Policy — ASG scaling that keeps a CloudWatch metric (e.g. CPU) at a target value.",
            "Savings Plans — hourly spend commitment; flexibility differs between Compute and EC2 Instance plans.",
            "Enhanced Networking (ENA) — supported network adapter; bandwidth is instance-specific.",
            "Spot Interruption — typically two minutes' notice for stop/terminate; hibernation starts immediately.",
            "Placement Group — logical grouping to control physical hardware placement for latency or HA.",
            "ELB Health Check — application-level health check that tells ASG if the app (not just VM) is healthy.",
            "AMI — Amazon Machine Image, the template (OS + pre-installed software) used to launch instances.",
        ],
    },
    "s3": {
        "title": "AWS S3: Storage Classes, Lifecycle, Security & Performance",
        "why": (
            "S3 appears in almost every AWS architecture question because it underpins storage, backups, static hosting, "
            "data lakes, and CI/CD artifacts. Interviewers test whether you know the cost/availability trade-offs across "
            "storage classes, how to enforce security at scale, and how to handle S3 in high-throughput systems. "
            "Misconfigurations have caused major data breaches at companies like Capital One — security knowledge is critical."
        ),
        "what": (
            "Amazon S3 (Simple Storage Service) is object storage launched in 2006. Unlike block "
            "storage (EBS), S3 stores objects (files + metadata) in buckets, accessible via HTTP/HTTPS from anywhere. "
            "Bucket naming and object limits depend on bucket type. Regional classes such as Standard are designed "
            "for 11-nines durability across multiple AZs; One Zone classes deliberately use one AZ. Durability is not "
            "availability or protection from authorized deletion. Use versioning and backups for those failure modes."
        ),
        "concepts": [
            {
                "name": "Storage Classes and Cost Trade-offs",
                "body": (
                    "S3 Standard is for frequent access with millisecond retrieval and no minimum storage duration. "
                    "Standard-IA charges retrieval fees and a 30-day minimum duration; compare the full access pattern "
                    "rather than assuming it is always cheaper. Rates vary by region, size and request volume. "
                    "S3 Glacier Instant Retrieval gives archive pricing with millisecond access — 90-day minimum. "
                    "Glacier Flexible Retrieval offers expedited, standard and bulk restore tiers with different "
                    "latency and charges. Deep Archive has longer restores and a 180-day minimum duration. "
                    "Intelligent-Tiering moves eligible objects by access pattern and charges monitoring fees. "
                    "Model restore time, request and retrieval charges, minimum billable size, and early deletion."
                ),
            },
            {
                "name": "Lifecycle Policies",
                "body": (
                    "Lifecycle rules automate object transitions and deletions based on age or prefix/tag filters. "
                    "A typical rule: transition to Standard-IA after 30 days, Glacier after 90 days, delete after 365. "
                    "Rules apply to current versions and/or noncurrent versions (when versioning is on). "
                    "Lifecycle transitions are one-way along supported paths. Restoring an archived object does not "
                    "permanently change its storage class; copying a restored object can create a Standard copy. "
                    "IA lifecycle transitions require at least 30 days' object age; IA storage then has its own "
                    "minimum billable duration. Object-size filters and noncurrent-version rules also matter."
                ),
            },
            {
                "name": "Bucket Policies, ACLs, and Security",
                "body": (
                    "S3 security has two layers: IAM (who can call S3) and Bucket Policy (what the bucket allows). "
                    "Bucket policies are resource-based JSON policies attached to the bucket — they can grant cross-account "
                    "access and restrict by VPC endpoint, IP, or condition. S3 Object Ownership with Bucket owner "
                    "enforced disables ACLs. Block Public Access is separate: BlockPublicAcls, IgnorePublicAcls, "
                    "BlockPublicPolicy and RestrictPublicBuckets limit public access, rather than disabling ACLs. "
                    "Always enable Block Public Access at the account level unless you intentionally host public content. "
                    "Server-side encryption: SSE-S3 (AWS manages keys), SSE-KMS (you control via KMS, adds cost and "
                    "API call limits), SSE-C (you provide keys per request). Enable default encryption + enforce TLS "
                    "via bucket policy with 'aws:SecureTransport: false' deny."
                ),
            },
            {
                "name": "Performance, Multipart Upload, and Transfer Acceleration",
                "body": (
                    "For general-purpose buckets, S3 supports at least 3,500 write and 5,500 read requests per second "
                    "per partitioned prefix; these are baseline performance guidance, not hard universal ceilings. "
                    "Scaling is gradual, so retry 503 SlowDown responses with backoff. Prefix distribution can help; "
                    "randomized names are not universally required. "
                    "Multipart Upload is mandatory for objects over 5 GB and recommended above 100 MB — it splits the "
                    "file into parts uploaded in parallel, then S3 assembles them. Failed parts can be retried without "
                    "re-uploading the whole file. S3 Transfer Acceleration routes uploads through AWS CloudFront edge "
                    "locations for faster global uploads — useful for users in different continents uploading large files. "
                    "One thing most engineers miss: incomplete multipart uploads accumulate storage costs invisibly — "
                    "always add a lifecycle rule to abort incomplete multipart uploads after 7 days."
                ),
            },
        ],
        "e2e": [
            "1. Client calls PutObject API with the bucket name, key (file path), and object data.",
            "2. S3 routes the request to the correct region based on the bucket's location.",
            "3. S3 authenticates and evaluates applicable policies, explicit denies and public-access controls; same-account and cross-account rules differ.",
            "4. If encryption is configured, S3 calls KMS to generate a data key (SSE-KMS) or uses its own key (SSE-S3).",
            "5. S3 stores the object according to the chosen storage class's multi-AZ or One Zone design.",
            "6. S3 returns an ETag and success response. Multipart, SSE-KMS and SSE-C ETags are not object MD5 checksums; use explicit checksum fields for integrity.",
            "7. If versioning is enabled, a new version ID is assigned; the old version is retained.",
            "8. Lifecycle rules and Intelligent Tiering monitor the object; transitions happen asynchronously.",
        ],
        "tasks": [
            {
                "name": "Task 1 (20 min): Set up lifecycle policy and verify transitions",
                "goal": "Understand how lifecycle rules move objects between storage classes",
                "steps": [
                    "Create an S3 bucket with versioning enabled.",
                    "Upload 5 test objects with the prefix 'archive/'.",
                    "Add a lifecycle rule: transition to Standard-IA after 30 days, Glacier after 90.",
                    "Use the S3 console to verify the rule is applied and check the estimated cost with the pricing calculator.",
                ],
            },
            {
                "name": "Task 2 (15 min): Lock down a bucket with a security policy",
                "goal": "Practice writing bucket policies that enforce encryption and deny public access",
                "steps": [
                    "Keep Object Ownership Bucket owner enforced (ACLs disabled) and all Block Public Access settings enabled.",
                    "Add a bucket policy that denies any request where aws:SecureTransport is false.",
                    "Use policy validation to check the insecure-transport deny; never send real credentials or sensitive objects over HTTP.",
                ],
            },
            {
                "name": "Task 3 (20 min): Write your answer to the S3 architecture question",
                "goal": "Practice a complete senior answer on S3 data lake design",
                "steps": [
                    "Question: 'Design an S3-based data lake for 10TB/day of log ingestion, 90-day retention, 5-year archive.'",
                    "Sketch the prefix structure, storage class transitions, and security controls.",
                    "Write a 3-minute verbal answer covering: ingestion, partitioning, lifecycle, cost estimate, access control.",
                ],
            },
        ],
        "key_terms": [
            "Bucket Policy — resource-based JSON policy on the bucket allowing cross-account, IP, or VPC conditions.",
            "Block Public Access — 4 account-level settings that override any public ACLs or policies.",
            "SSE-KMS — server-side encryption where you control the key via AWS KMS; adds API call cost.",
            "Multipart Upload — parallel upload of object parts, mandatory over 5 GB, retryable per part.",
            "Intelligent-Tiering — automatic access-tier changes for eligible objects; account for monitoring costs.",
            "Glacier Deep Archive — archive class with long restore times and minimum storage duration; verify current pricing.",
            "ETag — object-version identifier, not a universal MD5; multipart, SSE-KMS and SSE-C are non-MD5 cases.",
            "Presigned URL — time-limited URL that lets anyone download/upload without AWS credentials.",
            "CRR/SRR — Cross/Same Region Replication; requires versioning, used for compliance and latency.",
            "Transfer Acceleration — CloudFront edge network used to speed up uploads from global clients.",
        ],
    },
    "rds": {
        "title": "AWS RDS: Multi-AZ, Read Replicas, Performance & Backups",
        "why": (
            "RDS appears in almost every system design interview because every production app needs a database. "
            "Interviewers test whether you understand the difference between HA (Multi-AZ) and scalability (Read Replicas), "
            "how to size and tune RDS, and how to handle the RDS vs Aurora vs self-managed trade-off. "
            "Getting this wrong means either over-spending or building a system with a single point of failure."
        ),
        "what": (
            "Amazon RDS (Relational Database Service) is a managed database service that automates provisioning, patching, "
            "backups, and failover for supported engines including MySQL, PostgreSQL, MariaDB, Oracle, SQL Server and Db2. "
            "You still manage schema, queries, and indexes — RDS handles the OS and engine. It sits in your VPC, "
            "preferably in private subnets with public accessibility disabled and restricted security groups, making it easier to operate at "
            "scale than self-managed databases on EC2."
        ),
        "concepts": [
            {
                "name": "Multi-AZ Deployments",
                "body": (
                    "A traditional Multi-AZ DB instance has one synchronously replicated standby in another AZ. "
                    "That standby cannot serve reads. Failover changes the endpoint's DNS target; reconnect and "
                    "retry transactions safely instead of promising a fixed recovery time or universal zero loss. "
                    "A Multi-AZ DB cluster is different: one writer and two readable replicas in three AZs, using "
                    "semisynchronous replication with acknowledgement from at least one reader. Availability varies "
                    "by engine, version, class and region. Neither deployment is an Aurora cluster. "
                    "Test failover, DNS caching, connection pools and application recovery for the chosen deployment."
                ),
            },
            {
                "name": "Read Replicas",
                "body": (
                    "Read Replicas use asynchronous replication, which means there is replication lag — typically "
                    "milliseconds to seconds, but it can grow under load. Replica limits depend on engine and deployment. "
                    "Read Replicas offload SELECT queries and can support disaster recovery; they are not a substitute "
                    "for the automatic failover of a Multi-AZ DB instance. They have their own endpoint and your app must "
                    "be coded to use them. A Read Replica can be promoted to a standalone instance (becomes the new "
                    "primary after a disaster) but promotion breaks the replication chain permanently. "
                    "Cross-region Read Replicas add disaster recovery capability and reduce read latency for global users."
                ),
            },
            {
                "name": "Storage Types and Performance Tuning",
                "body": (
                    "RDS storage options include gp2, gp3, io1 and io2 Block Express where supported. "
                    "RDS gp3 baseline and provisionable IOPS depend on engine and allocated storage; do not copy "
                    "EC2 EBS limits into RDS. For example, MySQL/PostgreSQL gp3 baselines change at storage-size "
                    "thresholds. Compare the current RDS table, engine support, throughput, latency and cost. "
                    "Storage autoscaling grows storage when its free-space, elapsed-time and capacity conditions are met; enable it "
                    "to avoid the nightmare of running out of space at 3 AM. "
                    "Parameter Groups let you tune engine settings (e.g., innodb_buffer_pool_size, max_connections) "
                    "without restarting for dynamic parameters. One thing most engineers miss: RDS storage can only "
                    "be scaled up, never down — plan your starting size carefully."
                ),
            },
            {
                "name": "Backups, Snapshots, and Point-in-Time Recovery",
                "body": (
                    "RDS automated backups run daily during the backup window and retain transaction logs continuously, "
                    "enabling Point-in-Time Recovery (PITR) to any second within the retention period (1-35 days). "
                    "Manual snapshots persist until you delete them and are not subject to the retention period. "
                    "Restoring creates a NEW RDS instance — you cannot restore in-place — so your app must update "
                    "its connection string after a restore. "
                    "For cross-region DR, use supported snapshot copies or automated backup replication. "
                    "Check EarliestRestorableTime and LatestRestorableTime before choosing a PITR timestamp; "
                    "log upload and restore availability lag behind writes. Backup performance behavior depends on "
                    "engine and deployment, not just gp2. Test recovery and retain snapshots intentionally."
                ),
            },
        ],
        "e2e": [
            "1. App server calls the RDS endpoint (DNS-based, e.g. mydb.abc123.us-east-1.rds.amazonaws.com).",
            "2. Security group on RDS checks: is this source IP/SG allowed on port 5432/3306? Deny if not.",
            "3. RDS primary accepts the connection, authenticates via username/password or IAM auth token.",
            "4. App executes a write query — RDS primary processes it and writes to the gp3 EBS volume.",
            "5. A traditional Multi-AZ DB instance synchronously replicates to its standby; Multi-AZ DB clusters use a different semisynchronous design.",
            "6. If Read Replicas exist: the transaction log is asynchronously shipped to replicas (lag: ms to seconds).",
            "7. RDS sends transaction logs to S3 continuously for PITR backups.",
            "8. CloudWatch metrics (CPU, FreeStorageSpace, ReadIOPS, ReplicaLag) are emitted every 60 seconds for monitoring.",
        ],
        "tasks": [
            {
                "name": "Task 1 (20 min): Create an RDS instance with Multi-AZ and a Read Replica",
                "goal": "See the difference between Multi-AZ standby and Read Replica endpoints",
                "steps": [
                    "Choose a currently supported MySQL instance class for a traditional Multi-AZ DB instance in private subnets; estimate costs first.",
                    "Create a Read Replica from the primary — note it gets its own endpoint.",
                    "Check CloudWatch: find the ReplicaLag metric on the replica.",
                    "Trigger a failover via RDS console and measure how long DNS takes to update.",
                ],
            },
            {
                "name": "Task 2 (15 min): Test point-in-time recovery",
                "goal": "Understand PITR and why restoration creates a new instance",
                "steps": [
                    "Insert disposable test data and record timestamps before deleting it. Wait until LatestRestorableTime covers the intended recovery timestamp.",
                    "Restore to a timestamp before deletion within EarliestRestorableTime/LatestRestorableTime; observe a new instance and endpoint.",
                    "Connect to the restored instance and verify the deleted data is back.",
                ],
            },
            {
                "name": "Task 3 (20 min): Write your RDS vs Aurora answer",
                "goal": "Articulate when you'd choose each with trade-offs",
                "steps": [
                    "Question: 'When would you use RDS MySQL vs Aurora MySQL?'",
                    "Compare engine compatibility, measured workload performance, storage architecture, failover, operational needs and current regional pricing. Marketing ratios are not workload guarantees.",
                    "Use a hypothetical migration scenario unless you actually performed it; describe benchmarks and recovery tests rather than inventing employment experience.",
                ],
            },
        ],
        "key_terms": [
            "Multi-AZ — distinguish traditional DB instance standby from Multi-AZ DB cluster readable replicas and from Aurora.",
            "Read Replica — asynchronous read scaling or DR copy; replication lag and promotion behavior must be planned.",
            "PITR — Point-in-Time Recovery; restore to any second within retention period using transaction logs.",
            "Replication Lag — delay between primary write and replica reflecting it; monitor with CloudWatch.",
            "Storage Autoscaling — growth requires free-space, elapsed-time and capacity conditions; allocated storage cannot shrink in place.",
            "Parameter Group — engine configuration (buffer pool size, max connections) applied without full restart.",
            "IAM DB Authentication — short-lived authentication tokens for supported engines; token expiry is not the lifetime of an established DB connection.",
            "gp3 Storage — engine- and size-dependent RDS baselines and provisionable performance; consult the RDS storage table.",
            "Failover — endpoint target change and reconnection; measure recovery rather than promise a fixed duration.",
            "Subnet Group — set of subnets across multiple AZs where RDS can place instances for HA.",
        ],
    },
    "vpc": {
        "title": "AWS VPC: Subnets, Routing, Security Groups & NAT",
        "why": (
            "VPC is the networking foundation of every AWS deployment. Senior DevOps engineers are expected to design "
            "secure, scalable network topologies from scratch — not just click through the wizard. Interviewers test "
            "whether you understand the difference between Security Groups and NACLs, how routing works, how to "
            "design for multi-tier architectures, and how to connect to on-premises securely."
        ),
        "what": (
            "Amazon VPC (Virtual Private Cloud) is an isolated section of the AWS cloud where you control IP addressing, "
            "subnets, routing, and network access. Launched in 2009, it replaced EC2-Classic and became mandatory for "
            "many modern workloads. A default VPC may exist in a region, but can be deleted; do not depend on it. "
            "Use explicit address planning and an appropriate network design for production."
        ),
        "concepts": [
            {
                "name": "Subnets, CIDRs, and Availability Zones",
                "body": (
                    "A VPC spans a region; subnets are scoped to a single AZ. You define a VPC CIDR (e.g. 10.0.0.0/16 "
                    "giving 65,536 IPs) and carve it into subnets. Public subnets have a route to an Internet Gateway; "
                    "private subnets do not. AWS reserves 5 IPs in every subnet: .0 (network), .1 (VPC router), .2 "
                    "(DNS), .3 (future), .255 (broadcast) — so a /24 gives 251 usable IPs. "
                    "Plan CIDRs before deployment: the primary IPv4 CIDR cannot simply be resized; supported secondary "
                    "CIDRs can be associated subject to constraints. A /16 can be subdivided into /24 networks, subject "
                    "to subnet quotas. For multi-AZ, spread appropriate "
                    "subnet sizes across 3 AZs: one public, one private, one data subnet per AZ = 9 subnets total."
                ),
            },
            {
                "name": "Internet Gateway, NAT Gateway, and Routing",
                "body": (
                    "An Internet Gateway (IGW) enables two-way internet access for public subnets — one IGW per VPC, "
                    "horizontally scaled and fully managed. A NAT Gateway allows private subnet instances to initiate "
                    "outbound internet connections (e.g. download packages) without being reachable from the internet. "
                    "NAT gateway hourly, processing and data-transfer costs vary by region and design; model them first. "
                    "Route tables define where traffic goes: public subnets have 0.0.0.0/0 → IGW; private subnets have "
                    "0.0.0.0/0 → public NAT gateway. For zonal NAT gateways, deploy one per AZ for AZ-local egress "
                    "resilience. Regional NAT gateways are another option where available. Private NAT gateways "
                    "are for private connectivity and do not provide internet egress through an IGW. Public IPv4 "
                    "internet access also requires appropriate addresses, routes and security rules, not just an IGW."
                ),
            },
            {
                "name": "Security Groups vs Network ACLs",
                "body": (
                    "Security Groups are stateful firewalls attached to ENIs (instances, RDS, Lambda, ELB). "
                    "Stateful means if you allow inbound port 443, the return traffic is automatically allowed — "
                    "you only write rules for the direction of initiation. Security Groups support allow rules only. "
                    "NACLs are stateless firewalls on subnets — you must explicitly allow inbound AND outbound traffic, "
                    "including ephemeral ports (1024-65535) for return traffic. NACLs process rules in order (lowest "
                    "number first) and have an explicit DENY at the end. "
                    "In practice: Security Groups for instance-level control, NACLs as an extra subnet-level layer for "
                    "blocking known bad IPs or enforcing network segmentation. Gotcha: NACLs are stateless — forgetting "
                    "to allow outbound ephemeral ports is the #1 NACL misconfiguration."
                ),
            },
            {
                "name": "VPC Peering, Transit Gateway, and VPN/Direct Connect",
                "body": (
                    "VPC Peering connects two VPCs (same or different account, same or different region) with no "
                    "overlapping CIDRs. Peering is non-transitive — if A peers with B and B peers with C, A cannot "
                    "reach C via B. For hub-and-spoke at scale, use Transit Gateway which acts as a regional router "
                    "connecting hundreds of VPCs and on-premises networks. "
                    "VPN over the internet gives encrypted connectivity to on-premises in minutes but has variable "
                    "latency and tunnel-specific throughput limits. Direct Connect is a dedicated private connection "
                    "with location/port-specific bandwidth and provisioning lead time; it is not inherently encrypted. "
                    "Production pattern: Direct Connect for steady-state traffic + VPN as failover backup."
                ),
            },
        ],
        "e2e": [
            "1. Request arrives at the Internet Gateway (IGW) from the internet.",
            "2. IGW performs NAT for the public IP → private IP mapping and forwards to the VPC router.",
            "3. Route table on the public subnet routes the packet to the ALB's ENI.",
            "4. Security Group on the ALB checks: allow inbound 443 from 0.0.0.0/0? Yes — passes.",
            "5. ALB terminates TLS, selects a backend EC2 instance in a private subnet, forwards HTTP.",
            "6. Route table on the private subnet: no internet route — packet goes directly to EC2 via VPC internal routing.",
            "7. Security Group on EC2: allow inbound 8080 from ALB security group only — passes.",
            "8. EC2 can reach S3 through a supported VPC endpoint, or through public NAT/IGW routing; compare cost and policy requirements.",
        ],
        "tasks": [
            {
                "name": "Task 1 (20 min): Build a 3-tier VPC from scratch",
                "goal": "Practice the full VPC setup that appears in every architecture interview",
                "steps": [
                    "Create a sandbox VPC 10.0.0.0/16 with non-overlapping public, application and data /24 subnets across selected AZs; write each CIDR explicitly.",
                    "Attach an IGW and create a NAT Gateway in one public subnet.",
                    "Create route tables: public → IGW, private → NAT Gateway.",
                    "Use a small sandbox EC2 instance and approved access path to test HTTPS egress, routes and DNS; ICMP alone does not validate application connectivity.",
                ],
            },
            {
                "name": "Task 2 (15 min): Security Group chaining",
                "goal": "Understand how to use SG references instead of IP ranges",
                "steps": [
                    "Create ALB security group: allow 443 from 0.0.0.0/0.",
                    "Create App security group: allow 8080 from ALB-SG (not from 0.0.0.0/0).",
                    "Create DB security group: allow 5432 from App-SG only.",
                    "Verify connectivity by checking effective rules — this is the correct 3-tier pattern.",
                ],
            },
            {
                "name": "Task 3 (20 min): Design a multi-region VPC architecture",
                "goal": "Practice answering a common senior interview design question",
                "steps": [
                    "Question: 'Design the VPC architecture for a global fintech app with DR in two regions.'",
                    "Draw the CIDR plan (non-overlapping across regions for future peering).",
                    "Specify: which subnets are public/private, NAT Gateway per AZ, Direct Connect + VPN backup.",
                    "Write the answer as if presenting to a VP of Engineering.",
                ],
            },
        ],
        "key_terms": [
            "CIDR — Classless Inter-Domain Routing; defines IP range of VPC or subnet (e.g. 10.0.0.0/16).",
            "Internet Gateway — horizontally-scaled, HA component enabling public internet access for a VPC.",
            "NAT Gateway — managed service allowing private subnet outbound internet without inbound exposure.",
            "Route Table — set of rules that determine where network traffic from subnets is directed.",
            "Security Group — stateful instance-level firewall; allow rules only, return traffic auto-allowed.",
            "NACL — stateless subnet-level firewall; must allow both inbound and outbound including ephemeral ports.",
            "VPC Peering — direct connection between two VPCs; non-transitive, no overlapping CIDRs.",
            "Transit Gateway — regional hub router connecting VPCs and on-premises at scale.",
            "Ephemeral Ports — temporary high-number ports (1024-65535) used for return traffic in TCP connections.",
            "ENI — Elastic Network Interface, a virtual NIC attached to an EC2 instance or other service.",
        ],
    },
    "iam": {
        "title": "AWS IAM: Roles, Policies, Permissions & Security Best Practices",
        "why": (
            "IAM is the access control layer for every AWS service — misconfiguring it causes data breaches, compliance "
            "failures, and security incidents. Senior DevOps interviews always include IAM because it tests whether "
            "you apply least-privilege correctly, understand role chaining, and know how to secure CI/CD pipelines "
            "and cross-account access. Explain concrete permission paths rather than attributing complex incidents to one cause."
        ),
        "what": (
            "AWS IAM (Identity and Access Management) controls who (Identity) can do what (Action) on which resources "
            "(Resource) under what conditions (Condition). It has no cost and is global (not region-scoped). "
            "IAM has four main building blocks: Users (human or service identities with long-term credentials), "
            "Groups (collections of users sharing policies), Roles (temporary credential identities assumed by "
            "services or users), and Policies (JSON documents defining permissions)."
        ),
        "concepts": [
            {
                "name": "IAM Policies: Identity vs Resource-Based",
                "body": (
                    "Identity-based policies are attached to IAM users, groups, or roles and define what that identity "
                    "can do. Resource-based policies are attached to resources (S3 buckets, KMS keys, SQS queues) and "
                    "define who can access that resource. When evaluating access, AWS uses an explicit DENY wins rule: "
                    "if any policy denies the action, access is denied regardless of allows. "
                    "Managed policies (AWS-managed and customer-managed) can be attached to multiple identities. "
                    "Inline policies are embedded directly in a single identity and are deleted when the identity is "
                    "deleted — avoid inline policies in production, use customer-managed policies for reusability."
                ),
            },
            {
                "name": "IAM Roles and the Assume Role Mechanism",
                "body": (
                    "Roles provide temporary credentials via AWS STS (Security Token Service). When an EC2 instance, "
                    "Lambda function, or ECS task assumes a role, STS issues temporary access key + secret + session "
                    "token with a session duration determined by the API and role configuration. EC2 applications "
                    "use IMDS through the SDK credential chain; Lambda and ECS have different credential mechanisms. "
                    "Cross-account access works via role assumption: Account A creates a role trusting Account B, "
                    "Account B's principal calls sts:AssumeRole — no need to share access keys. "
                    "Role chaining (A assumes B, B assumes C) resets the session to 1 hour max regardless of the "
                    "original role's duration. Scope iam:PassRole to approved role ARNs and services: broad grants "
                    "can enable privilege escalation when combined with service permissions and a trusting role. "
                    "PassRole does not itself assume a role or universally bypass all policy controls."
                ),
            },
            {
                "name": "Least Privilege and Permission Boundaries",
                "body": (
                    "Least privilege means granting only the exact permissions needed — no wildcards (* actions), no "
                    "broad resource ARNs (*) unless justified. In practice: start with AWS managed policies for common "
                    "patterns, then restrict with resource ARNs and conditions. "
                    "Permission Boundaries are a guardrail attached to an IAM entity that sets the maximum permissions "
                    "available through its identity policies. Resource-policy grants have principal-specific "
                    "evaluation rules, so a boundary is not a universal replacement for resource-policy review. Used by security teams "
                    "to let developers manage their own IAM roles without escalating privileges. "
                    "IAM Access Analyzer scans resource policies and identifies external access — run it in every "
                    "account. IAM credential reports and Access Advisor show unused credentials and services."
                ),
            },
            {
                "name": "IAM in CI/CD and Service Accounts",
                "body": (
                    "For CI/CD pipelines, never use long-term IAM user credentials in GitHub Actions or Jenkins. "
                    "Use OIDC federation: GitHub Actions can assume an IAM role directly using a trust policy that "
                    "validates the GitHub OIDC token — no static credentials stored anywhere. "
                    "For EKS, use IRSA (IAM Roles for Service Accounts): annotate a Kubernetes service account "
                    "with an IAM role ARN, and pods get scoped temporary credentials automatically. "
                    "For multi-account organizations, use AWS Organizations SCPs (Service Control Policies) as "
                    "permission guardrails, not grants. SCPs apply to principals in member accounts, including root, "
                    "but not management-account principals or service-linked roles. Test restrictions in a small OU."
                ),
            },
        ],
        "e2e": [
            "1. The CLI resolves credentials through its configured provider chain; prefer federation or workload roles.",
            "2. On EC2, the SDK can retrieve temporary instance-role credentials through IMDSv2.",
            "3. For explicit role assumption, STS evaluates the applicable trust and identity policies.",
            "4. STS returns scoped temporary credentials; the SDK refreshes them as appropriate.",
            "5. The CLI signs the S3 service request using SigV4; it does not first ask IAM to pre-authorize it.",
            "6. AWS authenticates the principal and evaluates the service action, resources and applicable policies.",
            "7. Same-account identity/resource permissions generally combine as a union; boundaries, SCPs and cross-account rules add constraints.",
            "8. Applicable explicit denies override allows. Inspect the exact principal, action, resource and conditions when troubleshooting.",
        ],
        "tasks": [
            {
                "name": "Task 1 (20 min): Set up OIDC-based GitHub Actions IAM role",
                "goal": "Eliminate static credentials from CI/CD pipelines",
                "steps": [
                    "In IAM, create an OIDC identity provider for token.actions.githubusercontent.com.",
                    "Restrict the trust policy by token.actions.githubusercontent.com:aud and :sub to the intended repository and branch or protected environment.",
                    "In GitHub Actions workflow, use aws-actions/configure-aws-credentials with role-to-assume.",
                    "Verify the workflow can run aws s3 ls without any stored secrets.",
                ],
            },
            {
                "name": "Task 2 (15 min): Use IAM Access Analyzer",
                "goal": "Find overly permissive policies in your account",
                "steps": [
                    "Create an external-access analyzer in a sandbox; verify pricing because unused/internal-access analysis and other capabilities may have charges.",
                    "Review any findings — look for S3 buckets or roles accessible outside your account.",
                    "Use the policy validator to check a sample JSON policy for best practice violations.",
                ],
            },
            {
                "name": "Task 3 (20 min): Write your IAM least-privilege answer",
                "goal": "Practice a complete senior answer on IAM security design",
                "steps": [
                    "Question: 'How do you ensure least privilege across 50 AWS accounts in an organization?'",
                    "Structure your answer: Organizations SCPs as guardrails, Permission Boundaries for delegation, IRSA for pods, OIDC for CI/CD, Access Analyzer for drift detection.",
                    "Use a hypothetical regional service restriction; account for global services such as IAM and aws:RequestedRegion exceptions. Do not invent past employment experience.",
                ],
            },
        ],
        "key_terms": [
            "Least Privilege — granting only the minimum permissions required; no wildcard actions or resources.",
            "STS AssumeRole — API call that exchanges identity for temporary credentials (key + secret + token).",
            "Permission Boundary — limit on identity-policy grants; evaluate resource-based principal grants and explicit denies separately.",
            "OIDC Federation — trust external identity providers (GitHub, Google) to issue IAM temporary credentials.",
            "IRSA — IAM Roles for Service Accounts; scopes IAM permissions per Kubernetes pod via service account annotation.",
            "SCP — member-account permission guardrail, not a grant; management-account and service-linked-role exceptions apply.",
            "IAM Access Analyzer — policy validation and access analysis; capability, region and pricing vary.",
            "Resource-Based Policy — policy attached to a resource (S3, KMS) granting cross-account access.",
            "Explicit Deny — any DENY in any policy overrides any number of allows; used as a hard block.",
            "IMDS — Instance Metadata Service (169.254.169.254); EC2 instances retrieve temp credentials from here.",
        ],
    },
    "lambda": {
        "title": "AWS Lambda: Serverless, Event-Driven Architecture & Performance",
        "why": (
            "Lambda is central to modern serverless and event-driven architectures. Interviewers ask about it because "
            "it tests whether you understand cold starts, concurrency limits, event source mappings, and when "
            "serverless is actually the wrong choice. Companies like Netflix and Airbnb run millions of Lambda "
            "invocations daily — understanding its limits separates juniors from seniors."
        ),
        "what": (
            "AWS Lambda runs your code in response to events without provisioning or managing servers. You pay only "
            "according to requests, duration and enabled features. Provisioned capacity, storage and supporting "
            "services can cost money while idle. Managed and custom runtimes support several languages; check the "
            "runtime support lifecycle. Keep durable state outside execution environments. Conventional functions "
            "have a 15-minute invocation limit; specialized execution modes have different documented limits."
        ),
        "concepts": [
            {
                "name": "Cold Starts and Execution Environment",
                "body": (
                    "A cold start occurs when Lambda initializes a new execution environment: download code, start "
                    "runtime, run initialization code. This adds 100ms to 1s+ of latency depending on runtime and "
                    "package size and initialization work; measure rather than ranking runtimes universally. "
                    "Warm reuse is opportunistic, with no guaranteed 15-minute lifetime. Provisioned Concurrency "
                    "pre-initializes configured capacity, but spillover and environment resets still require careful "
                    "latency testing. SnapStart snapshots initialized supported runtimes, including supported Java, "
                    "Python and .NET versions. It applies to published versions/aliases with compatibility constraints; "
                    "check current runtime, package and region support rather than describing it as Java-only."
                ),
            },
            {
                "name": "Concurrency, Throttling, and Reserved Concurrency",
                "body": (
                    "Account-wide default concurrency limit is 1000 simultaneous executions per region (soft limit, "
                    "can be raised; new accounts may have lower quotas). Synchronous throttles can return 429. "
                    "Reserved Concurrency sets a cap on a specific function (e.g., max 100 concurrent) — protects "
                    "downstream systems and reserves account capacity for that function, reducing the unreserved pool. "
                    "Provisioned Concurrency pre-initializes N environments at all times. "
                    "For Lambda asynchronous invocation, function errors are retried twice by default. Throttling "
                    "and system errors instead requeue with backoff for up to six hours by default, subject to "
                    "configured event age/retries. Configure failure destinations or DLQs and idempotent handlers. "
                    "SQS event source mappings follow queue visibility/redrive behavior, not this async policy."
                ),
            },
            {
                "name": "Event Source Mappings and Triggers",
                "body": (
                    "Lambda can be triggered synchronously (API Gateway, ALB — caller waits) or asynchronously "
                    "(S3, SNS, EventBridge — Lambda queued internally). For stream sources (Kinesis, DynamoDB Streams, "
                    "and queues such as SQS), Lambda uses event source mappings to poll and process batches. "
                    "SQS Standard supports up to 10,000 records per batch, FIFO up to 10; payload limits may reduce "
                    "the actual count. Function timeout must not exceed visibility timeout. AWS recommends at least "
                    "six times the function timeout plus batching window; this does not guarantee no duplicates. "
                    "Use idempotency and partial batch failure responses. "
                    "Kinesis trigger: shards are processed in order; one concurrent execution per shard by default — "
                    "parallelization factor can increase concurrency per shard within ordering constraints. Failure "
                    "handling and on-failure destinations depend on the event source and configuration."
                ),
            },
            {
                "name": "VPC, Layers, and Deployment Limits",
                "body": (
                    "By default Lambda runs outside your VPC and cannot access private RDS or ElastiCache. Enabling "
                    "VPC mode attaches Lambda to your private subnets via ENIs — this historically caused cold start "
                    "delays; Hyperplane ENIs improve connection management but do not guarantee zero startup work. "
                    "A public subnet alone does not give a function a public IP or internet egress. "
                    "ZIP functions support up to five layers: direct API/SDK/console ZIP upload is 50 MB compressed, "
                    "and the expanded package including layers/custom runtimes is 250 MB. Container images have "
                    "a separate size limit. /tmp is configurable from 512 MB to 10,240 MB. Verify account and "
                    "execution-mode quotas in the current documentation. "
                    "Lambda Power Tuning (open-source tool) helps find the optimal memory setting — more memory "
                    "means more CPU, which often makes functions faster AND cheaper."
                ),
            },
        ],
        "e2e": [
            "1. API Gateway receives an HTTP request, authenticates via Cognito or Lambda Authorizer.",
            "2. API Gateway invokes Lambda synchronously, passing the event object (headers, body, path).",
            "3. Lambda service checks concurrency limits — throttles if exceeded (returns 429 to API GW).",
            "4. If warm: reuses existing execution environment. If cold: downloads code, starts runtime, runs init code.",
            "5. Your handler function runs, processes the event — reads from DynamoDB, writes to S3.",
            "6. If in a VPC: all traffic to RDS/ElastiCache goes via the private subnet's ENI.",
            "7. Handler returns a response object; Lambda serializes it to JSON and returns to API Gateway.",
            "8. API Gateway formats the HTTP response and sends back to the client. CloudWatch Logs captures stdout.",
        ],
        "tasks": [
            {
                "name": "Task 1 (20 min): Measure cold start vs warm start latency",
                "goal": "Quantify cold start impact and understand Provisioned Concurrency",
                "steps": [
                    "Deploy a Python Lambda with a 100ms sleep in init code (outside the handler).",
                    "Invoke it 10 times in a row — measure duration vs init duration in CloudWatch.",
                    "Enable Provisioned Concurrency = 1 and measure again — no init duration on warm invocations.",
                    "Compare on-demand execution with provisioned concurrency cost; reserved concurrency itself is not billed capacity.",
                ],
            },
            {
                "name": "Task 2 (15 min): Set up SQS trigger with dead letter queue",
                "goal": "Understand batch processing and failure handling",
                "steps": [
                    "Create an SQS queue and a DLQ. Set DLQ as the SQS redrive policy after 3 failures.",
                    "Create a Lambda with the SQS queue as event source (batch size 10).",
                    "Use disposable messages and deterministic test failures. Observe visibility, receive counts and maxReceiveCount redrive rather than assuming exactly three retries; enable partial batch responses.",
                ],
            },
            {
                "name": "Task 3 (20 min): Write your Lambda vs ECS answer",
                "goal": "Practice the most common Lambda trade-off question",
                "steps": [
                    "Question: 'When would you use Lambda instead of ECS Fargate for a microservice?'",
                    "Write answer covering: execution time (Lambda max 15 min), traffic pattern (Lambda ideal for spiky), state (both stateless), cost (Lambda: pay per ms, ECS: pay per task running), cold starts.",
                    "Label examples hypothetical unless they are your own real experience.",
                ],
            },
        ],
        "key_terms": [
            "Cold Start — initialization work for a new execution environment; measure runtime/package-specific latency.",
            "Provisioned Concurrency — pre-initialized configured capacity; costs while idle and does not cover arbitrary spillover.",
            "Reserved Concurrency — max concurrent executions for a function; protects downstream and reserves capacity.",
            "Event Source Mapping — Lambda polls streams (SQS, Kinesis, DDB Streams) and processes batches.",
            "DLQ — failure queue; Lambda async DLQs and SQS redrive are different mechanisms.",
            "Lambda Layer — shared code package (libraries, runtimes) reusable across multiple functions.",
            "VPC Mode — attaches Lambda to your private subnets via ENIs; required for RDS/ElastiCache access.",
            "SnapStart — initialized-environment snapshots for supported runtimes/versions; verify compatibility, not Java-only.",
            "Concurrency Limit — regional/account and function limits; defaults and throttle handling vary by invocation mode.",
            "Lambda Power Tuning — open-source tool that finds the optimal memory-to-cost setting for your function.",
        ],
    },
}  # end LESSONS


# Concept-level diagrams — 4 per topic, one per concept, building progressively
CONCEPT_DIAGRAMS = {
    "ec2": [
        # Concept 1: Instance Families
        """flowchart LR
    T[t3 family\nBurstable CPU] -->|Dev / Test| UC1[Low sustained\nworkloads]
    M[m6i family\nGeneral Purpose] -->|App servers| UC2[Balanced\nCPU + RAM]
    C[c6i family\nCompute Optimized] -->|CI runners\nML inference| UC3[High CPU\nworkloads]
    R[r6i family\nMemory Optimized] -->|Databases\nRedis| UC4[High RAM\nworkloads]""",
        # Concept 2: Purchasing Options
        """flowchart TD
    OD[On-Demand\nFull price\nNo commitment] -->|Unpredictable\ntraffic| USE1[Dev / spiky\nworkloads]
    RI[Reserved 1-3yr\nConditional discounts] -->|Stable baseline| USE2[Always-on\nproduction]
    SP[Savings Plans\nFlexible commit] -->|Mixed instance\ntypes| USE3[Flexible\nbaseline]
    SPOT[Spot\nVariable discounts\nInterruption risk] -->|Fault tolerant| USE4[Batch / CI\nstateless workers]""",
        # Concept 3: Auto Scaling Groups
        """flowchart TD
    CW[CloudWatch\nCPU greater than 70 percent] -->|scale-out alarm| ASG[Auto Scaling Group]
    ASG -->|launch| EC2a[EC2 AZ-1]
    ASG -->|launch| EC2b[EC2 AZ-2]
    ASG -->|launch| EC2c[EC2 AZ-3]
    LT[Launch Template\nAMI + type + SG] --> ASG
    ALB[Load Balancer] -->|ELB health check| ASG
    ASG -->|policy specific warmup or cooldown| ASG""",
        # Concept 4: Placement Groups
        """flowchart TD
    CL[Cluster\nClose placement in one AZ] -->|Low latency| HPC[HPC / tightly\ncoupled apps]
    SP2[Spread\nDifferent racks\nmax 7 per AZ] -->|Critical instances\nmust not fail together| HA[HA critical\nservices]
    PA[Partition\nGroups of racks] -->|Large distributed\nsystems| DIST[Hadoop\nCassandra Kafka]""",
    ],
    "s3": [
        # Concept 1: Storage Classes
        """flowchart LR
    HOT[S3 Standard\nFrequent access] -->|Configured eligible lifecycle rule| IA[Standard-IA\nRetrieval charges]
    IA -->|Supported transition| GI[Glacier Instant\nMillisecond access]
    GI -->|Supported transition| GF[Glacier Flexible\nRestore tiers]
    GF -->|Supported transition| DA[Deep Archive\nLong restore time]""",
        # Concept 2: Lifecycle Policies
        """flowchart TD
    UPLOAD[Object Uploaded\nto S3 Standard] -->|Day 0| STD[Standard Storage]
    STD -->|Day 30 rule| IA2[Transition to\nStandard-IA]
    IA2 -->|Day 90 rule| GLAC[Transition to\nGlacier]
    GLAC -->|Day 365 rule| DEL[Delete Object]
    TAG[Prefix or Tag\nFilter] -->|applies to| STD
    VER[Noncurrent\nVersions] -->|separate rule| IA2""",
        # Concept 3: Security
        """flowchart TD
    REQ[Incoming Request] --> IAM[Authenticate and evaluate\napplicable IAM and resource policies]
    IAM -->|permitted| BPA[Block Public Access\nlimits public grants]
    OWN[Object Ownership\nBucket owner enforced\nACLs disabled] --> IAM
    BPA -->|permitted| ENC[SSE Encryption\nSSE-S3 or SSE-KMS]
    ENC --> OBJ[Object Stored]
    IAM -->|explicit deny or no applicable allow| BLOCK[Access denied]
    BPA -->|blocked public access| BLOCK""",
        # Concept 4: Performance & Multipart
        """flowchart LR
    FILE[Large File\ngreater than 100MB] --> P1[Part 1]
    FILE --> P2[Part 2]
    FILE --> P3[Part 3]
    FILE --> P4[Part N]
    P1 -->|parallel upload| S3[S3 Bucket]
    P2 -->|parallel upload| S3
    P3 -->|parallel upload| S3
    P4 -->|parallel upload| S3
    S3 -->|CompleteMultipartUpload| DONE[Single Object\nAssembled]""",
    ],
    "rds": [
        # Concept 1: Multi-AZ
        """flowchart TD
    APP[Application] --> EP[RDS Endpoint\nDNS based]
    EP --> PRI[Primary\nAZ-1]
    PRI -->|synchronous replication\nDB instance deployment| STB[Standby\nAZ-2\nNo reads]
    PRI -->|write ack only\nafter standby confirms| APP
    FAIL[Primary fails] -->|Failover and DNS change\nmeasure recovery| STB
    STB -->|becomes new primary| EP
    CLUSTER[Different deployment\nMulti-AZ DB cluster] --> READERS[Two readable replicas\nSemisynchronous replication]""",
        # Concept 2: Read Replicas
        """flowchart TD
    PRI2[Primary\nRDS Instance] -->|asynchronous\nreplication| RR1[Read Replica 1\nown endpoint]
    PRI2 -->|asynchronous\nreplication| RR2[Read Replica 2\ncross region]
    APP2[App Writes] --> PRI2
    APP3[App Reads] --> RR1
    APP3 --> RR2
    LAG[Replication Lag\nms to seconds] -.->|monitor| RR1
    RR1 -->|promote to standalone\nbreaks replication| NEW[New Primary\nafter DR]""",
        # Concept 3: Storage Types
        """flowchart LR
    GP2[gp2 SSD\n3 IOPS per GB\nburst to 3000] -->|Good for\nsmall DBs| USE1[Variable workloads]
    GP3[gp3 SSD\nEngine and size dependent limits] -->|Compare measured cost and latency| USE2[Production DBs]
    IO1[io1 or io2 Block Express\nSupported provisioned IOPS] -->|High throughput| USE3[OLTP\nhigh traffic]
    AUTO[Storage Autoscaling\nFree space and time conditions] --> GP3""",
        # Concept 4: Backups & PITR
        """flowchart TD
    PRI3[RDS Primary] -->|continuous\ntransaction logs| S3B[S3 Backup Storage]
    PRI3 -->|daily snapshot\nbackup window| SNAP[Automated Snapshot\n1-35 day retention]
    SNAP -->|manual copy| XSNAP[Cross-Region\nSnapshot for DR]
    S3B -->|timestamp within restorable window| NEW2[New RDS Instance\ndifferent endpoint]
    SNAP -->|restore| NEW2
    NOTE[Cannot restore\nin-place] -.-> NEW2""",
    ],
    "vpc": [
        # Concept 1: Subnets & CIDRs
        """flowchart TD
    VPC[VPC\n10.0.0.0 per 16\n65536 IPs] --> PUB1[Public Subnet\n10.0.1.0 per 24\nAZ-1]
    VPC --> PUB2[Public Subnet\n10.0.2.0 per 24\nAZ-2]
    VPC --> PRIV1[Private Subnet\n10.0.3.0 per 24\nAZ-1]
    VPC --> PRIV2[Private Subnet\n10.0.4.0 per 24\nAZ-2]
    PUB1 -->|internet route| IGW2[Internet\nGateway]
    PRIV1 -->|no internet route| LOCAL[Local VPC\ntraffic only]""",
        # Concept 2: IGW, NAT & Routing
        """flowchart TD
    INET[Internet] --> IGW3[Internet Gateway\n1 per VPC HA]
    IGW3 --> ALB2[ALB in\nPublic Subnet]
    ALB2 --> EC2P[EC2 in\nPrivate Subnet]
    EC2P -->|outbound only\n0.0.0.0 per 0| NAT2[NAT Gateway\nin Public Subnet]
    NAT2 --> IGW3
    IGW3 --> INET
    COST[Zonal public NAT example\nHourly and processing cost varies] -.-> NAT2""",
        # Concept 3: Security Groups vs NACLs
        """flowchart TD
    REQ2[Inbound Request] --> NACL2[NACL\nStateless\nSubnet level\nRules in order]
    NACL2 -->|rule allows| SG2[Security Group\nStateful\nInstance level\nAllow only]
    SG2 -->|allow| EC2SG[EC2 Instance]
    EC2SG -->|return traffic\nauto allowed by SG| CLIENT[Client]
    NACL2 -->|must allow\nephemeral ports\n1024-65535| CLIENT
    NACL2 -->|explicit deny| DROP[Dropped]""",
        # Concept 4: VPC Peering & Transit Gateway
        """flowchart TD
    TGW[Transit Gateway\nRegional Hub Router] --> VPC1[VPC A\nProd]
    TGW --> VPC2[VPC B\nDev]
    TGW --> VPC3[VPC C\nShared Services]
    TGW --> ONPREM[On-Premises\nvia VPN or DX]
    NOTE2[VPC Peering\nnon-transitive\nA-B and B-C\ndoes not mean A-C] -.-> TGW
    DX[Direct Connect\ndedicated line\nconsistent latency] --> TGW""",
    ],
    "iam": [
        # Concept 1: Policy Types
        """flowchart TD
    ID[IAM Identity\nUser or Role] -->|Identity-based policy\nwhat can this do| ACT[Actions Allowed\nor Denied]
    RES[AWS Resource\nS3 or KMS] -->|Resource-based policy\nwho can access this| ACT
    DENY[Explicit DENY\nin any policy] -->|overrides all allows| BLOCK2[Access Denied]
    COND[Condition\nIP or MFA or VPC] -->|restricts| ACT
    SCP[SCP\nOrg-level guardrail] -->|outermost limit| ACT""",
        # Concept 2: IAM Roles & AssumeRole
        """flowchart TD
    EC2R[EC2 Instance] -->|SDK retrieves role credentials| META[IMDSv2]
    META --> ROLE[IAM Role]
    CICD[GitHub Actions] -->|OIDC token| STS2
    LAMBDA[Lambda Function] -->|AssumeRole auto| STS2
    STS2 -->|Temporary credentials\nAPI dependent duration| ROLE
    ROLE -->|scoped permissions| S3R[S3 Access]
    ROLE -->|scoped permissions| DDBR[DynamoDB Access]
    TRUST[Trust Policy\nwho can assume] --> ROLE""",
        # Concept 3: Least Privilege & Permission Boundaries
        """flowchart TD
    MAXP[Permission Boundary\nIdentity policy limit] -->|limits identity grants| ROLE2[IAM Role]
    ROLE2 -->|attached policy\nmust be within boundary| EFF[Effective Permissions\nintersection of both]
    SEC[Security Team\nsets boundary] --> MAXP
    DEV[Developer\nsets role policy] --> ROLE2
    EFF -->|also evaluate resource grants and denies| ACCESS[Actual Access Granted]
    ANAL[IAM Access Analyzer\nfinds external access] -.->|scan| ROLE2""",
        # Concept 4: OIDC & CI/CD
        """flowchart TD
    GHA[GitHub Actions\nWorkflow] -->|OIDC JWT token| IDP[OIDC Identity Provider\nin AWS IAM]
    IDP -->|validate token\ncheck repo and branch| STS3[STS AssumeRoleWithWebIdentity]
    STS3 -->|temp credentials\nno stored secrets| ROLE3[IAM Role]
    ROLE3 --> ECR[Push to ECR]
    ROLE3 --> ECS2[Deploy to ECS]
    NOKV[No Access Keys\nstored in GitHub] -.->|security benefit| GHA""",
    ],
    "lambda": [
        # Concept 1: Cold Starts
        """flowchart TD
    REQ3[First Invocation\ncold start] --> INIT[Init Phase\ndownload code\nstart runtime\nrun init code]
    INIT -->|Measure initialization latency| HANDLER[Handler runs]
    REQ4[Next Invocation\nReuse not guaranteed] -->|possible warm reuse| HANDLER
    HANDLER --> RESP[Response]
    PC[Provisioned Concurrency\npre-initialized capacity] -->|Reduce startup latency\nIdle capacity cost| HANDLER
    SNAP2[SnapStart\nSupported Java Python and NET\nPublished versions] --> INIT""",
        # Concept 2: Concurrency & Throttling
        """flowchart TD
    REQS[Concurrent requests] --> LIMIT[Account regional quota\nCheck Service Quotas]
    LIMIT -->|within limit| EXEC[Concurrent Executions]
    LIMIT -->|over limit| THROTTLE[429 TooManyRequests]
    RC[Reserved Concurrency\nReserve and cap] -->|protect downstream| EXEC
    PROVCON[Provisioned Concurrency\nPre-initialized capacity] --> EXEC
    THROTTLE -->|async throttles and system errors| RETRY[Requeue with backoff\nConfigured maximum event age]
    ERR[Async function errors] -->|Default two retries| DEST[Configured failure destination]""",
        # Concept 3: Event Source Mappings
        """flowchart LR
    SYNC[Synchronous\nAPI GW or ALB] -->|caller waits\nfor response| LAMBDA2[Lambda]
    ASYNC[Asynchronous\nS3 or SNS or EventBridge] -->|queued internally\ncaller gets 202| LAMBDA2
    STREAM[Stream Polling\nSQS or Kinesis\nor DDB Streams] -->|event source mapping\nbatch processing| LAMBDA2
    LAMBDA2 --> SUCCESS[Source specific success handling]
    LAMBDA2 -->|source specific retries and failure policy| DLQ2[Destination or queue redrive]""",
        # Concept 4: VPC & Layers
        """flowchart TD
    LAMBDA3[Lambda Function] -->|VPC mode| ENI[Hyperplane ENI\nprivate subnet]
    ENI --> RDS2[RDS in\nprivate subnet]
    ENI --> REDIS[ElastiCache\nRedis]
    LAYER1[Layer 1\nnumpy or pandas] --> LAMBDA3
    LAYER2[Layer 2\ncustom runtime] --> LAMBDA3
    LAMBDA3 -->|ZIP plus layers expanded| LIMIT2[250 MB expanded\n50 MB direct ZIP upload]
    TMP[tmp storage\n512MB to 10GB] --> LAMBDA3""",
    ],
}  # end CONCEPT_DIAGRAMS


REVIEWED_AT = "2026-09-25"

REFERENCES = {
    "ec2": [
        "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-performance-instances-unlimited-mode.html",
        "https://docs.aws.amazon.com/autoscaling/ec2/userguide/ec2-auto-scaling-scaling-cooldowns.html",
        "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/placement-groups.html",
        "https://aws.amazon.com/ec2/pricing/",
    ],
    "s3": [
        "https://docs.aws.amazon.com/AmazonS3/latest/userguide/about-object-ownership.html",
        "https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html",
        "https://docs.aws.amazon.com/AmazonS3/latest/API/API_Object.html",
        "https://docs.aws.amazon.com/AmazonS3/latest/userguide/optimizing-performance.html",
        "https://aws.amazon.com/s3/pricing/",
    ],
    "rds": [
        "https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.MultiAZ.html",
        "https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/multi-az-db-clusters-concepts.html",
        "https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_Storage.html",
        "https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_PIT.html",
        "https://aws.amazon.com/rds/pricing/",
    ],
    "vpc": [
        "https://docs.aws.amazon.com/vpc/latest/userguide/vpc-nat-gateway.html",
        "https://docs.aws.amazon.com/vpc/latest/userguide/vpc-cidr-blocks.html",
        "https://docs.aws.amazon.com/vpc/latest/userguide/VPC_Security.html",
        "https://aws.amazon.com/vpc/pricing/",
    ],
    "iam": [
        "https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_evaluation-logic.html",
        "https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps.html",
        "https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html",
        "https://aws.amazon.com/iam/access-analyzer/pricing/",
    ],
    "lambda": [
        "https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html",
        "https://docs.aws.amazon.com/lambda/latest/dg/snapstart.html",
        "https://docs.aws.amazon.com/lambda/latest/dg/invocation-async-error-handling.html",
        "https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-configure.html",
        "https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtime-environment.html",
        "https://aws.amazon.com/lambda/pricing/",
    ],
}

CLEANUP = {
    "ec2": [
        "Set the lab ASG desired/minimum capacity to zero, then delete the ASG and launch template.",
        "Delete the lab ALB, listeners and target groups; terminate standalone lab instances.",
        "Check for retained EBS volumes/snapshots, public IPv4/Elastic IP allocations and log groups; remove only lab resources.",
    ],
    "s3": [
        "Delete every version and delete marker of disposable objects; abort incomplete multipart uploads.",
        "Remove the empty lab bucket and any lab-only policies or keys according to their deletion safeguards.",
        "Check minimum storage-duration charges before transitioning/deleting; never test with production data.",
    ],
    "rds": [
        "Delete lab read replicas and restored instances, then the primary; verify deletion protection deliberately.",
        "Decide whether a final snapshot is needed; retained snapshots and automated backups can continue to incur charges.",
        "Remove disposable snapshots, parameter/subnet groups, secrets and lab-only security groups after confirming no shared dependencies.",
    ],
    "vpc": [
        "Delete lab workloads, load balancers, endpoints and NAT gateways; NAT and public IPv4 billing persists while allocated.",
        "Release lab Elastic IPs once detached. Remove lab routes, gateways, subnets, security groups and the VPC in dependency order.",
        "Do not remove shared network resources. Confirm the lab resource inventory and billing after cleanup.",
    ],
    "iam": [
        "Remove only the test workflow role's trust grants/policies and delete the role.",
        "Delete lab-only analyzers and identity providers only after checking they are not shared.",
        "Remove test credentials if any were created; prefer short-lived federation and never publish credentials in logs.",
    ],
    "lambda": [
        "Disable and delete the lab event source mapping before deleting its source queue.",
        "Remove provisioned concurrency, function versions/aliases, functions and lab layers.",
        "Delete disposable SQS queues/DLQs, log groups, test roles and any lab NAT gateways; confirm no billable resources remain.",
    ],
}

for _topic, _lesson in LESSONS.items():
    _lesson["reviewed_at"] = REVIEWED_AT
    _lesson["references"] = REFERENCES[_topic]
    _lesson["safety"] = (
        "Use a disposable sandbox account, least-privilege permissions and synthetic data only. "
        "Do not run these labs against production. Estimate current regional prices and set a budget alert first "
        "(alerts are not spending caps); free-tier eligibility is not assumed. Review quotas and supported "
        "engine/runtime/instance combinations. Keep network access private and restricted. "
        "If you cannot authorize the cost or required access, complete a paper design instead. "
        "Time estimates are practice estimates, not resource provisioning or billing guarantees."
    )
    _lesson["cleanup"] = CLEANUP[_topic]
    for _task in _lesson["tasks"]:
        _task["minutes"] = 15 if "(15 min)" in _task["name"] else 20


def get_lesson(topic):
    """Return pre-written lesson for the topic, or None if not found."""
    topic_words = topic.lower().replace(":", " ").split()
    for key, lesson in LESSONS.items():
        if key in topic_words:
            return lesson
    return None


def get_concept_diagrams(topic):
    """Return list of 4 concept diagrams for the topic, or empty list."""
    topic_words = topic.lower().replace(":", " ").split()
    for key, diagrams in CONCEPT_DIAGRAMS.items():
        if key in topic_words:
            return diagrams
    return []
