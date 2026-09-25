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
        "as AWS's first major service. You choose the CPU, memory, storage, and network capacity; AWS handles "
        "the underlying physical hardware. EC2 fits into the AWS ecosystem as the compute layer that runs "
        "containers, application servers, batch jobs, and anything else needing a full OS."
    ),
    "concepts": [
        {
            "name": "Instance Families and Types",
            "body": (
                "EC2 instances are grouped by family: General Purpose (t3, m6i), Compute Optimized (c6i), "
                "Memory Optimized (r6i, x2idn), Storage Optimized (i3, d3), and Accelerated (p4, g5 for GPU). "
                "Within each family, size goes from nano to 112xlarge, doubling CPU and RAM at each step. "
                "The t-family uses burstable performance: you earn CPU credits when idle and spend them during "
                "spikes — ideal for dev/test but dangerous for production workloads with sustained load. "
                "Interview trap: 'When would you NOT use a t3?' Answer: any sustained CPU workload — a t3.medium "
                "at 100% CPU will burn credits and throttle to 20% baseline, causing mysterious slowdowns."
            )
        },
        {
            "name": "Purchasing Options: On-Demand, Reserved, Spot, Savings Plans",
            "body": (
                "On-Demand costs the most but has no commitment — good for unpredictable or short workloads. "
                "Reserved Instances give up to 72% discount for 1 or 3-year commitments; Standard RIs lock you "
                "to instance type, Convertible RIs let you change family but give less discount (~66%). "
                "Spot Instances use spare AWS capacity at up to 90% discount but can be interrupted with 2-minute "
                "notice — perfect for batch jobs, rendering, and stateless workers. "
                "Savings Plans (Compute and EC2) are more flexible than RIs: you commit to $/hour spend, not "
                "a specific instance. Real-world rule: baseline load on Reserved/Savings Plans, variable load "
                "on On-Demand, fault-tolerant batch on Spot."
            )
        },
        {
            "name": "Auto Scaling Groups (ASG)",
            "body": (
                "An ASG automatically adds or removes EC2 instances based on demand, maintaining a min/max/desired "
                "count. Scaling policies include Target Tracking (keep CPU at 60%), Step Scaling (add 2 instances "
                "when CPU > 80%), and Scheduled Scaling (scale up at 9 AM). "
                "Launch Templates define what instance to launch — type, AMI, security groups, user data. "
                "Cooldown period (default 300s) prevents thrashing by waiting after a scale event before the "
                "next one. Critical gotcha: ASG health checks can be EC2-level (is the VM running?) or ELB-level "
                "(is the app responding?). Use ELB health checks in production — EC2-level passes even if your "
                "app is crashed."
            )
        },
        {
            "name": "Placement Groups and Networking",
            "body": (
                "Placement Groups control where AWS physically places your instances. Cluster placement (same rack, "
                "same AZ) gives lowest latency and highest throughput — used for HPC and tightly coupled apps. "
                "Spread placement puts instances on different hardware racks — max 7 per AZ, used for critical "
                "instances that must not fail together. Partition placement divides instances into groups of "
                "racks — used for Hadoop, Cassandra. "
                "Enhanced Networking (ENA) gives up to 100 Gbps, SR-IOV bypasses hypervisor for lower latency. "
                "One thing most engineers miss: you cannot add a running instance to a Cluster placement group "
                "without stopping and restarting it."
            )
        }
    ],
    "e2e": [
        "1. You submit a RunInstances API call specifying AMI, instance type, subnet, security group, and key pair.",
        "2. EC2 scheduler finds physical hardware in the target AZ with enough capacity.",
        "3. A hypervisor (AWS uses Nitro hypervisor) allocates CPU, RAM, and network resources.",
        "4. The AMI (backed by an EBS snapshot) is used to create a root EBS volume.",
        "5. The instance boots, runs the user data script, and registers with any attached load balancer.",
        "6. The ELB health check starts polling; after 2 consecutive passes the instance receives traffic.",
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
                "Terminate both — note the cost difference in the pricing calculator."
            ]
        },
        {
            "name": "Task 2 (15 min): Set up an Auto Scaling Group",
            "goal": "Understand how ASG integrates with ALB and health checks",
            "steps": [
                "Create a Launch Template with Amazon Linux 2, t3.micro, and a simple web server user-data script.",
                "Create an ASG with min=1, max=3, desired=2, attached to an ALB.",
                "Set a Target Tracking policy for CPU at 50% and observe the desired count."
            ]
        },
        {
            "name": "Task 3 (20 min): Write out your answer to this interview question",
            "goal": "Practice structuring a complete Senior DevOps answer about cost optimization",
            "steps": [
                "Question: 'Your EC2 bill is $50k/month. How do you reduce it by 40%?'",
                "Write your answer covering: Savings Plans, right-sizing, Spot for batch, ASG scheduling.",
                "Time yourself — a strong answer should take 3-4 minutes to deliver."
            ]
        }
    ],
    "key_terms": [
        "Nitro Hypervisor — AWS's lightweight bare-metal hypervisor, replaces Xen, gives near-native performance.",
        "CPU Credits — burstable performance tokens earned at idle, spent at high CPU on t-family instances.",
        "Launch Template — versioned config (AMI, type, SG, user data) used by ASG and EC2 Fleet.",
        "Target Tracking Policy — ASG scaling that keeps a CloudWatch metric (e.g. CPU) at a target value.",
        "Savings Plans — flexible commitment to $/hour spend, applies across instance families and regions.",
        "Enhanced Networking (ENA) — single-root I/O virtualization for up to 100 Gbps, lower latency.",
        "Spot Interruption — 2-minute notice before AWS reclaims a Spot Instance for on-demand use.",
        "Placement Group — logical grouping to control physical hardware placement for latency or HA.",
        "ELB Health Check — application-level health check that tells ASG if the app (not just VM) is healthy.",
        "AMI — Amazon Machine Image, the template (OS + pre-installed software) used to launch instances.",
    ]
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
        "Amazon S3 (Simple Storage Service) is object storage launched in 2006 — AWS's oldest service. Unlike block "
        "storage (EBS), S3 stores objects (files + metadata) in buckets, accessible via HTTP/HTTPS from anywhere. "
        "Objects can be up to 5 TB, buckets are globally unique by name, and S3 provides 99.999999999% (11 nines) "
        "durability by automatically replicating data across at least 3 AZs within a region."
    ),
    "concepts": [
        {
            "name": "Storage Classes and Cost Trade-offs",
            "body": (
                "S3 Standard ($0.023/GB/month) is for frequently accessed data — millisecond retrieval, no minimum "
                "storage duration. Standard-IA (Infrequent Access, $0.0125/GB) saves 46% but charges a retrieval "
                "fee ($0.01/GB) and has a 30-day minimum — wrong choice if you access data weekly. "
                "S3 Glacier Instant Retrieval gives archive pricing with millisecond access — 90-day minimum. "
                "Glacier Flexible Retrieval takes 1-12 hours and costs $0.004/GB — for DR backups you hope to "
                "never restore. Glacier Deep Archive at $0.00099/GB is the cheapest but 12+ hour retrieval — "
                "compliance archives only. Intelligent Tiering automatically moves objects between tiers based "
                "on access patterns — best for unpredictable workloads, has a monitoring fee of $0.0025/1000 objects."
            )
        },
        {
            "name": "Lifecycle Policies",
            "body": (
                "Lifecycle rules automate object transitions and deletions based on age or prefix/tag filters. "
                "A typical rule: transition to Standard-IA after 30 days, Glacier after 90 days, delete after 365. "
                "Rules apply to current versions and/or noncurrent versions (when versioning is on). "
                "You cannot transition from Glacier back to Standard via a lifecycle rule — only retrieval works. "
                "Interview gotcha: if you transition an object to Standard-IA before 30 days, AWS still charges "
                "you for the minimum 30-day storage. Always model your access patterns before choosing IA classes."
            )
        },
        {
            "name": "Bucket Policies, ACLs, and Security",
            "body": (
                "S3 security has two layers: IAM (who can call S3) and Bucket Policy (what the bucket allows). "
                "Bucket policies are resource-based JSON policies attached to the bucket — they can grant cross-account "
                "access and restrict by VPC, IP, or condition. ACLs are legacy and AWS recommends disabling them "
                "via S3 Block Public Access (4 settings: block all public, block new public, ignore public ACLs, restrict public buckets). "
                "Always enable Block Public Access at the account level unless you intentionally host public content. "
                "Server-side encryption: SSE-S3 (AWS manages keys), SSE-KMS (you control via KMS, adds cost and "
                "API call limits), SSE-C (you provide keys per request). Enable default encryption + enforce TLS "
                "via bucket policy with 'aws:SecureTransport: false' deny."
            )
        },
        {
            "name": "Performance, Multipart Upload, and Transfer Acceleration",
            "body": (
                "S3 scales automatically but has per-prefix request rate limits: 3500 PUT/COPY/POST/DELETE and "
                "5500 GET/HEAD per second per prefix. If you have one prefix (one folder) with thousands of requests, "
                "you'll see 503 SlowDown errors. Fix: use multiple prefixes (randomize the key prefix). "
                "Multipart Upload is mandatory for objects over 5 GB and recommended above 100 MB — it splits the "
                "file into parts uploaded in parallel, then S3 assembles them. Failed parts can be retried without "
                "re-uploading the whole file. S3 Transfer Acceleration routes uploads through AWS CloudFront edge "
                "locations for faster global uploads — useful for users in different continents uploading large files. "
                "One thing most engineers miss: incomplete multipart uploads accumulate storage costs invisibly — "
                "always add a lifecycle rule to abort incomplete multipart uploads after 7 days."
            )
        }
    ],
    "e2e": [
        "1. Client calls PutObject API with the bucket name, key (file path), and object data.",
        "2. S3 routes the request to the correct region based on the bucket's location.",
        "3. S3 checks IAM permissions + bucket policy — denies if either fails.",
        "4. If encryption is configured, S3 calls KMS to generate a data key (SSE-KMS) or uses its own key (SSE-S3).",
        "5. S3 stores the object and automatically replicates it across at least 3 AZs within the region.",
        "6. S3 returns an ETag (MD5 of the object) and HTTP 200 to confirm durability.",
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
                "Use the S3 console to verify the rule is applied and check the estimated cost with the pricing calculator."
            ]
        },
        {
            "name": "Task 2 (15 min): Lock down a bucket with a security policy",
            "goal": "Practice writing bucket policies that enforce encryption and deny public access",
            "steps": [
                "Enable S3 Block Public Access on a test bucket.",
                "Add a bucket policy that denies any request where aws:SecureTransport is false.",
                "Verify by trying to access the bucket via HTTP — should get 403."
            ]
        },
        {
            "name": "Task 3 (20 min): Write your answer to the S3 architecture question",
            "goal": "Practice a complete senior answer on S3 data lake design",
            "steps": [
                "Question: 'Design an S3-based data lake for 10TB/day of log ingestion, 90-day retention, 5-year archive.'",
                "Sketch the prefix structure, storage class transitions, and security controls.",
                "Write a 3-minute verbal answer covering: ingestion, partitioning, lifecycle, cost estimate, access control."
            ]
        }
    ],
    "key_terms": [
        "Bucket Policy — resource-based JSON policy on the bucket allowing cross-account, IP, or VPC conditions.",
        "Block Public Access — 4 account-level settings that override any public ACLs or policies.",
        "SSE-KMS — server-side encryption where you control the key via AWS KMS; adds API call cost.",
        "Multipart Upload — parallel upload of object parts, mandatory over 5 GB, retryable per part.",
        "Intelligent Tiering — auto-moves objects between access tiers; monitoring fee of $0.0025/1000 objects.",
        "Glacier Deep Archive — $0.00099/GB, 12hr retrieval, for compliance data you never expect to restore.",
        "ETag — MD5 checksum S3 returns after successful PutObject; use for data integrity verification.",
        "Presigned URL — time-limited URL that lets anyone download/upload without AWS credentials.",
        "CRR/SRR — Cross/Same Region Replication; requires versioning, used for compliance and latency.",
        "Transfer Acceleration — CloudFront edge network used to speed up uploads from global clients.",
    ]
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
        "backups, and failover for MySQL, PostgreSQL, MariaDB, Oracle, SQL Server, and Amazon Aurora. "
        "You still manage schema, queries, and indexes — RDS handles the OS and engine. It sits in your VPC, "
        "in private subnets, accessible only via security groups, making it significantly easier to operate at "
        "scale than self-managed databases on EC2."
    ),
    "concepts": [
        {
            "name": "Multi-AZ Deployments",
            "body": (
                "Multi-AZ creates a synchronous standby replica in a different Availability Zone. Every write to "
                "the primary is synchronously replicated to the standby before acknowledging the write — this means "
                "zero data loss (RPO = 0). Failover is automatic: if the primary fails, Route 53 updates the "
                "endpoint DNS within 60-120 seconds and the standby becomes the new primary. "
                "Critical: the standby cannot serve read traffic — it exists purely for failover. "
                "Interview trap: 'Can you query the Multi-AZ standby?' No — that's what Read Replicas are for. "
                "Failover also triggers during maintenance, instance class changes, and storage scaling."
            )
        },
        {
            "name": "Read Replicas",
            "body": (
                "Read Replicas use asynchronous replication, which means there is replication lag — typically "
                "milliseconds to seconds, but can spike under heavy write load. You can have up to 15 Read Replicas "
                "for MySQL/PostgreSQL (Aurora allows 15 per cluster). Read Replicas are used to offload "
                "SELECT queries from the primary, not for HA — they have their own endpoint and your app must "
                "be coded to use them. A Read Replica can be promoted to a standalone instance (becomes the new "
                "primary after a disaster) but promotion breaks the replication chain permanently. "
                "Cross-region Read Replicas add disaster recovery capability and reduce read latency for global users."
            )
        },
        {
            "name": "Storage Types and Performance Tuning",
            "body": (
                "RDS offers three storage types: gp2 (burstable SSD, 3 IOPS/GB baseline, up to 3000 burst), "
                "gp3 (baseline 3000 IOPS, scale independently to 16000 IOPS), and io1 (Provisioned IOPS, up to "
                "256000 IOPS for high-throughput workloads). For most production databases, gp3 is the right "
                "choice: cheaper than io1, more consistent than gp2. "
                "Storage autoscaling automatically increases storage when free space drops below 10% — enable it "
                "to avoid the nightmare of running out of space at 3 AM. "
                "Parameter Groups let you tune engine settings (e.g., innodb_buffer_pool_size, max_connections) "
                "without restarting for dynamic parameters. One thing most engineers miss: RDS storage can only "
                "be scaled up, never down — plan your starting size carefully."
            )
        },
        {
            "name": "Backups, Snapshots, and Point-in-Time Recovery",
            "body": (
                "RDS automated backups run daily during the backup window and retain transaction logs continuously, "
                "enabling Point-in-Time Recovery (PITR) to any second within the retention period (1-35 days). "
                "Manual snapshots persist until you delete them and are not subject to the retention period. "
                "Restoring creates a NEW RDS instance — you cannot restore in-place — so your app must update "
                "its connection string after a restore. "
                "Backup to cross-region: use manual snapshot copy or enable automated backup replication to a "
                "second region for DR. For Aurora, backups are continuous and stored in S3 automatically — "
                "no performance impact, unlike RDS where backups can cause I/O pauses on gp2 storage."
            )
        }
    ],
    "e2e": [
        "1. App server calls the RDS endpoint (DNS-based, e.g. mydb.abc123.us-east-1.rds.amazonaws.com).",
        "2. Security group on RDS checks: is this source IP/SG allowed on port 5432/3306? Deny if not.",
        "3. RDS primary accepts the connection, authenticates via username/password or IAM auth token.",
        "4. App executes a write query — RDS primary processes it and writes to the gp3 EBS volume.",
        "5. If Multi-AZ: the write is synchronously replicated to the standby in AZ-2 before acknowledgment.",
        "6. If Read Replicas exist: the transaction log is asynchronously shipped to replicas (lag: ms to seconds).",
        "7. RDS sends transaction logs to S3 continuously for PITR backups.",
        "8. CloudWatch metrics (CPU, FreeStorageSpace, ReadIOPS, ReplicaLag) are emitted every 60 seconds for monitoring.",
    ],
    "tasks": [
        {
            "name": "Task 1 (20 min): Create an RDS instance with Multi-AZ and a Read Replica",
            "goal": "See the difference between Multi-AZ standby and Read Replica endpoints",
            "steps": [
                "Create a MySQL RDS db.t3.micro with Multi-AZ enabled in a VPC with private subnets.",
                "Create a Read Replica from the primary — note it gets its own endpoint.",
                "Check CloudWatch: find the ReplicaLag metric on the replica.",
                "Trigger a failover via RDS console and measure how long DNS takes to update."
            ]
        },
        {
            "name": "Task 2 (15 min): Test point-in-time recovery",
            "goal": "Understand PITR and why restoration creates a new instance",
            "steps": [
                "On your RDS instance, insert test data, wait 2 minutes, then delete it.",
                "Restore to point-in-time (1 minute before deletion) — watch it create a new instance.",
                "Connect to the restored instance and verify the deleted data is back."
            ]
        },
        {
            "name": "Task 3 (20 min): Write your RDS vs Aurora answer",
            "goal": "Articulate when you'd choose each with trade-offs",
            "steps": [
                "Question: 'When would you use RDS MySQL vs Aurora MySQL?'",
                "Write a structured answer: cost (Aurora 20% more), performance (Aurora 5x faster), storage (Aurora auto up to 128TB), replication (Aurora 6-way, RDS async).",
                "Add a real scenario: 'At my last company we migrated from RDS to Aurora when we hit 10000 IOPS and needed instant failover under 30 seconds.'"
            ]
        }
    ],
    "key_terms": [
        "Multi-AZ — synchronous standby in a different AZ; automatic failover, RPO=0, RTO=60-120s.",
        "Read Replica — async copy for read scaling; can have replication lag; not for HA.",
        "PITR — Point-in-Time Recovery; restore to any second within retention period using transaction logs.",
        "Replication Lag — delay between primary write and replica reflecting it; monitor with CloudWatch.",
        "Storage Autoscaling — automatically grows EBS volume when free space < 10%; cannot shrink.",
        "Parameter Group — engine configuration (buffer pool size, max connections) applied without full restart.",
        "IAM DB Authentication — use IAM tokens instead of passwords to connect to RDS; rotates automatically.",
        "gp3 Storage — baseline 3000 IOPS, independently scalable, cheaper than io1 for most workloads.",
        "Failover — automatic promotion of Multi-AZ standby; DNS TTL causes 60-120s connection interruption.",
        "Subnet Group — set of subnets across multiple AZs where RDS can place instances for HA.",
    ]
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
        "production workloads. Every AWS account gets a default VPC (172.31.0.0/16) in each region — but for "
        "production you always create custom VPCs with proper CIDR planning."
    ),
    "concepts": [
        {
            "name": "Subnets, CIDRs, and Availability Zones",
            "body": (
                "A VPC spans a region; subnets are scoped to a single AZ. You define a VPC CIDR (e.g. 10.0.0.0/16 "
                "giving 65,536 IPs) and carve it into subnets. Public subnets have a route to an Internet Gateway; "
                "private subnets do not. AWS reserves 5 IPs in every subnet: .0 (network), .1 (VPC router), .2 "
                "(DNS), .3 (future), .255 (broadcast) — so a /24 gives 251 usable IPs. "
                "Interview rule: always plan CIDRs before deployment — once a VPC CIDR is set, you cannot change "
                "it. A /16 VPC with /24 subnets gives 256 subnets × 251 IPs each. For multi-AZ, spread identical "
                "subnet sizes across 3 AZs: one public, one private, one data subnet per AZ = 9 subnets total."
            )
        },
        {
            "name": "Internet Gateway, NAT Gateway, and Routing",
            "body": (
                "An Internet Gateway (IGW) enables two-way internet access for public subnets — one IGW per VPC, "
                "horizontally scaled and fully managed. A NAT Gateway allows private subnet instances to initiate "
                "outbound internet connections (e.g. download packages) without being reachable from the internet. "
                "NAT Gateway costs ~$0.045/hour + $0.045/GB processed — for high-throughput workloads this adds up. "
                "Route tables define where traffic goes: public subnets have 0.0.0.0/0 → IGW; private subnets have "
                "0.0.0.0/0 → NAT Gateway. NAT Gateway is AZ-scoped — for true HA deploy one per AZ, each serving "
                "the private subnet in its own AZ."
            )
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
            )
        },
        {
            "name": "VPC Peering, Transit Gateway, and VPN/Direct Connect",
            "body": (
                "VPC Peering connects two VPCs (same or different account, same or different region) with no "
                "overlapping CIDRs. Peering is non-transitive — if A peers with B and B peers with C, A cannot "
                "reach C via B. For hub-and-spoke at scale, use Transit Gateway which acts as a regional router "
                "connecting hundreds of VPCs and on-premises networks. "
                "VPN over the internet gives encrypted connectivity to on-premises in minutes but has variable "
                "latency and max 1.25 Gbps. Direct Connect is a dedicated private line from your data center "
                "to AWS — consistent latency, up to 100 Gbps, but takes weeks to provision. "
                "Production pattern: Direct Connect for steady-state traffic + VPN as failover backup."
            )
        }
    ],
    "e2e": [
        "1. Request arrives at the Internet Gateway (IGW) from the internet.",
        "2. IGW performs NAT for the public IP → private IP mapping and forwards to the VPC router.",
        "3. Route table on the public subnet routes the packet to the ALB's ENI.",
        "4. Security Group on the ALB checks: allow inbound 443 from 0.0.0.0/0? Yes — passes.",
        "5. ALB terminates TLS, selects a backend EC2 instance in a private subnet, forwards HTTP.",
        "6. Route table on the private subnet: no internet route — packet goes directly to EC2 via VPC internal routing.",
        "7. Security Group on EC2: allow inbound 8080 from ALB security group only — passes.",
        "8. EC2 makes an outbound call to S3 — private subnet route 0.0.0.0/0 → NAT Gateway → IGW → S3.",
    ],
    "tasks": [
        {
            "name": "Task 1 (20 min): Build a 3-tier VPC from scratch",
            "goal": "Practice the full VPC setup that appears in every architecture interview",
            "steps": [
                "Create VPC 10.0.0.0/16 with 3 public subnets (10.0.1-3.0/24) and 3 private subnets (10.0.4-6.0/24).",
                "Attach an IGW and create a NAT Gateway in one public subnet.",
                "Create route tables: public → IGW, private → NAT Gateway.",
                "Launch an EC2 in the private subnet and verify it can reach the internet via NAT (ping 8.8.8.8)."
            ]
        },
        {
            "name": "Task 2 (15 min): Security Group chaining",
            "goal": "Understand how to use SG references instead of IP ranges",
            "steps": [
                "Create ALB security group: allow 443 from 0.0.0.0/0.",
                "Create App security group: allow 8080 from ALB-SG (not from 0.0.0.0/0).",
                "Create DB security group: allow 5432 from App-SG only.",
                "Verify connectivity by checking effective rules — this is the correct 3-tier pattern."
            ]
        },
        {
            "name": "Task 3 (20 min): Design a multi-region VPC architecture",
            "goal": "Practice answering a common senior interview design question",
            "steps": [
                "Question: 'Design the VPC architecture for a global fintech app with DR in two regions.'",
                "Draw the CIDR plan (non-overlapping across regions for future peering).",
                "Specify: which subnets are public/private, NAT Gateway per AZ, Direct Connect + VPN backup.",
                "Write the answer as if presenting to a VP of Engineering."
            ]
        }
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
    ]
},

"iam": {
    "title": "AWS IAM: Roles, Policies, Permissions & Security Best Practices",
    "why": (
        "IAM is the access control layer for every AWS service — misconfiguring it causes data breaches, compliance "
        "failures, and security incidents. Senior DevOps interviews always include IAM because it tests whether "
        "you apply least-privilege correctly, understand role chaining, and know how to secure CI/CD pipelines "
        "and cross-account access. The Capital One breach, the Uber breach — both had IAM at the root."
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
            )
        },
        {
            "name": "IAM Roles and the Assume Role Mechanism",
            "body": (
                "Roles provide temporary credentials via AWS STS (Security Token Service). When an EC2 instance, "
                "Lambda function, or ECS task assumes a role, STS issues temporary access key + secret + session "
                "token (valid 15 min to 12 hours). Applications use the instance metadata service (IMDS) to "
                "retrieve these automatically. "
                "Cross-account access works via role assumption: Account A creates a role trusting Account B, "
                "Account B's principal calls sts:AssumeRole — no need to share access keys. "
                "Role chaining (A assumes B, B assumes C) resets the session to 1 hour max regardless of the "
                "original role's duration. Gotcha: never give iam:PassRole broadly — it lets someone grant any "
                "role to any service, effectively bypassing all permission boundaries."
            )
        },
        {
            "name": "Least Privilege and Permission Boundaries",
            "body": (
                "Least privilege means granting only the exact permissions needed — no wildcards (* actions), no "
                "broad resource ARNs (*) unless justified. In practice: start with AWS managed policies for common "
                "patterns, then restrict with resource ARNs and conditions. "
                "Permission Boundaries are a guardrail attached to an IAM entity that sets the maximum permissions "
                "it can ever have — even if a policy attached to it allows more. Used by central security teams "
                "to let developers manage their own IAM roles without escalating privileges. "
                "IAM Access Analyzer scans resource policies and identifies external access — run it in every "
                "account. IAM credential reports and Access Advisor show unused credentials and services."
            )
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
                "the outermost guardrail — they override everything, even admin users."
            )
        }
    ],
    "e2e": [
        "1. Developer runs `aws s3 ls` — AWS CLI reads credentials from ~/.aws/credentials or environment.",
        "2. CLI calls IAM to evaluate: does this identity have s3:ListAllMyBuckets permission?",
        "3. IAM evaluates all attached policies + any resource policies. Explicit DENY anywhere → 403.",
        "4. If the identity is an EC2 instance role: CLI hits IMDS (169.254.169.254) to get temp credentials.",
        "5. STS verifies the role's trust policy allows the EC2 service to assume it.",
        "6. STS issues temporary credentials (key + secret + token) valid for 1-6 hours.",
        "7. CLI signs the S3 API request with SigV4 using the temporary credentials.",
        "8. S3 validates the signature and evaluates S3 bucket policy + IAM policy — access granted or denied.",
    ],
    "tasks": [
        {
            "name": "Task 1 (20 min): Set up OIDC-based GitHub Actions IAM role",
            "goal": "Eliminate static credentials from CI/CD pipelines",
            "steps": [
                "In IAM, create an OIDC identity provider for token.actions.githubusercontent.com.",
                "Create an IAM role with a trust policy allowing your GitHub repo to assume it.",
                "In GitHub Actions workflow, use aws-actions/configure-aws-credentials with role-to-assume.",
                "Verify the workflow can run aws s3 ls without any stored secrets."
            ]
        },
        {
            "name": "Task 2 (15 min): Use IAM Access Analyzer",
            "goal": "Find overly permissive policies in your account",
            "steps": [
                "Enable IAM Access Analyzer in your account (it's free).",
                "Review any findings — look for S3 buckets or roles accessible outside your account.",
                "Use the policy validator to check a sample JSON policy for best practice violations."
            ]
        },
        {
            "name": "Task 3 (20 min): Write your IAM least-privilege answer",
            "goal": "Practice a complete senior answer on IAM security design",
            "steps": [
                "Question: 'How do you ensure least privilege across 50 AWS accounts in an organization?'",
                "Structure your answer: Organizations SCPs as guardrails, Permission Boundaries for delegation, IRSA for pods, OIDC for CI/CD, Access Analyzer for drift detection.",
                "Include a real example: 'We used SCPs to block any IAM action outside us-east-1 for compliance.'"
            ]
        }
    ],
    "key_terms": [
        "Least Privilege — granting only the minimum permissions required; no wildcard actions or resources.",
        "STS AssumeRole — API call that exchanges identity for temporary credentials (key + secret + token).",
        "Permission Boundary — max-permissions guardrail; identity cannot exceed what the boundary allows.",
        "OIDC Federation — trust external identity providers (GitHub, Google) to issue IAM temporary credentials.",
        "IRSA — IAM Roles for Service Accounts; scopes IAM permissions per Kubernetes pod via service account annotation.",
        "SCP — Service Control Policy; org-level guardrail that overrides all IAM policies in member accounts.",
        "IAM Access Analyzer — identifies resources accessible outside your account or org; free, run always.",
        "Resource-Based Policy — policy attached to a resource (S3, KMS) granting cross-account access.",
        "Explicit Deny — any DENY in any policy overrides any number of allows; used as a hard block.",
        "IMDS — Instance Metadata Service (169.254.169.254); EC2 instances retrieve temp credentials from here.",
    ]
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
        "per 1ms of execution time and per invocation — zero cost when idle. Lambda supports Node.js, Python, "
        "Java, Go, Ruby, .NET, and custom runtimes. Functions are stateless by design — any state must be "
        "externalized to DynamoDB, S3, or ElastiCache. Maximum execution time is 15 minutes per invocation."
    ),
    "concepts": [
        {
            "name": "Cold Starts and Execution Environment",
            "body": (
                "A cold start occurs when Lambda initializes a new execution environment: download code, start "
                "runtime, run initialization code. This adds 100ms to 1s+ of latency depending on runtime and "
                "package size. Java and .NET have the worst cold starts; Python and Node.js the best. "
                "Once warm, Lambda reuses the environment for subsequent invocations (within ~15 minutes of idle). "
                "Mitigation: Provisioned Concurrency pre-warms environments so there are no cold starts — adds "
                "cost but critical for latency-sensitive APIs. Lambda Snap Start (Java) takes a snapshot of the "
                "initialized environment and restores it, reducing Java cold starts by up to 90%."
            )
        },
        {
            "name": "Concurrency, Throttling, and Reserved Concurrency",
            "body": (
                "Account-wide default concurrency limit is 1000 simultaneous executions per region (soft limit, "
                "can be raised). When limit is hit, Lambda throttles — returns 429 TooManyRequests. "
                "Reserved Concurrency sets a cap on a specific function (e.g., max 100 concurrent) — protects "
                "downstream systems from being overwhelmed and ensures other functions have remaining capacity. "
                "Provisioned Concurrency pre-initializes N environments at all times. "
                "For async invocations (SNS, EventBridge), throttled events are retried up to 2 times with "
                "exponential backoff, then go to a Dead Letter Queue (DLQ) if configured."
            )
        },
        {
            "name": "Event Source Mappings and Triggers",
            "body": (
                "Lambda can be triggered synchronously (API Gateway, ALB — caller waits) or asynchronously "
                "(S3, SNS, EventBridge — Lambda queued internally). For stream sources (Kinesis, DynamoDB Streams, "
                "SQS), Lambda uses event source mappings — Lambda polls the stream and processes batches. "
                "SQS trigger: Lambda reads up to 10,000 messages/batch, deletes on success; visibility timeout "
                "must be 6x the function timeout to prevent reprocessing. "
                "Kinesis trigger: shards are processed in order; one concurrent execution per shard by default — "
                "increasing shard count is the way to increase parallelism. DLQ or on-failure destination captures "
                "failed batches."
            )
        },
        {
            "name": "VPC, Layers, and Deployment Limits",
            "body": (
                "By default Lambda runs outside your VPC and cannot access private RDS or ElastiCache. Enabling "
                "VPC mode attaches Lambda to your private subnets via ENIs — this historically caused cold start "
                "delays but AWS fixed this in 2020 with hyperplane ENIs that are pre-provisioned. "
                "Lambda Layers package shared code/libraries (up to 5 layers per function, 250 MB total). "
                "Key limits: 250 MB deployment package (zipped), 512 MB /tmp storage (configurable to 10 GB), "
                "15 minute timeout, 10 GB memory. "
                "Lambda Power Tuning (open-source tool) helps find the optimal memory setting — more memory "
                "means more CPU, which often makes functions faster AND cheaper."
            )
        }
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
                "Calculate cost difference between reserved and on-demand concurrency."
            ]
        },
        {
            "name": "Task 2 (15 min): Set up SQS trigger with dead letter queue",
            "goal": "Understand batch processing and failure handling",
            "steps": [
                "Create an SQS queue and a DLQ. Set DLQ as the SQS redrive policy after 3 failures.",
                "Create a Lambda with the SQS queue as event source (batch size 10).",
                "Deploy a version that fails 50% of invocations — watch failed messages go to DLQ after 3 retries."
            ]
        },
        {
            "name": "Task 3 (20 min): Write your Lambda vs ECS answer",
            "goal": "Practice the most common Lambda trade-off question",
            "steps": [
                "Question: 'When would you use Lambda instead of ECS Fargate for a microservice?'",
                "Write answer covering: execution time (Lambda max 15 min), traffic pattern (Lambda ideal for spiky), state (both stateless), cost (Lambda: pay per ms, ECS: pay per task running), cold starts.",
                "Give a real example where each is the right choice."
            ]
        }
    ],
    "key_terms": [
        "Cold Start — initialization latency when Lambda creates a new execution environment; worst in Java/.NET.",
        "Provisioned Concurrency — pre-initialized environments eliminating cold starts; costs even when idle.",
        "Reserved Concurrency — max concurrent executions for a function; protects downstream and reserves capacity.",
        "Event Source Mapping — Lambda polls streams (SQS, Kinesis, DDB Streams) and processes batches.",
        "DLQ — Dead Letter Queue; captures events that failed after all retries for async/stream invocations.",
        "Lambda Layer — shared code package (libraries, runtimes) reusable across multiple functions.",
        "VPC Mode — attaches Lambda to your private subnets via ENIs; required for RDS/ElastiCache access.",
        "Snap Start — Java-only; snapshots initialized JVM and restores on cold start, reducing latency 90%.",
        "Concurrency Limit — 1000 default per region; throttled invocations get 429 response.",
        "Lambda Power Tuning — open-source tool that finds the optimal memory-to-cost setting for your function.",
    ]
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
    RI[Reserved 1-3yr\n72 percent savings] -->|Stable baseline| USE2[Always-on\nproduction]
    SP[Savings Plans\nFlexible commit] -->|Mixed instance\ntypes| USE3[Flexible\nbaseline]
    SPOT[Spot\n90 percent savings\n2min warning] -->|Fault tolerant| USE4[Batch / CI\nstateless workers]""",

    # Concept 3: Auto Scaling Groups
    """flowchart TD
    CW[CloudWatch\nCPU greater than 70 percent] -->|scale-out alarm| ASG[Auto Scaling Group]
    ASG -->|launch| EC2a[EC2 AZ-1]
    ASG -->|launch| EC2b[EC2 AZ-2]
    ASG -->|launch| EC2c[EC2 AZ-3]
    LT[Launch Template\nAMI + type + SG] --> ASG
    ALB[Load Balancer] -->|ELB health check| ASG
    ASG -->|cooldown 300s| ASG""",

    # Concept 4: Placement Groups
    """flowchart TD
    CL[Cluster\nSame rack same AZ] -->|Lowest latency\nhighest throughput| HPC[HPC / tightly\ncoupled apps]
    SP2[Spread\nDifferent racks\nmax 7 per AZ] -->|Critical instances\nmust not fail together| HA[HA critical\nservices]
    PA[Partition\nGroups of racks] -->|Large distributed\nsystems| DIST[Hadoop\nCassandra Kafka]""",
],

"s3": [
    # Concept 1: Storage Classes
    """flowchart LR
    HOT[S3 Standard\n0.023 per GB\nms retrieval] -->|30 days no access| IA[Standard-IA\n0.0125 per GB\nretrieval fee]
    IA -->|90 days| GI[Glacier Instant\n0.004 per GB\nms retrieval]
    GI -->|180 days| GF[Glacier Flexible\n1-12hr retrieval]
    GF -->|365 days| DA[Deep Archive\n0.001 per GB\n12hr retrieval]""",

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
    REQ[Incoming Request] --> IAM[IAM Policy Check\nwho is calling]
    IAM -->|allow| BP[Bucket Policy Check\nwhat is allowed]
    BP -->|allow| BPA[Block Public Access\naccount level]
    BPA -->|pass| ENC[SSE Encryption\nSSE-S3 or SSE-KMS]
    ENC --> OBJ[Object Stored]
    IAM -->|deny| BLOCK[403 Denied]
    BP -->|deny| BLOCK""",

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
    PRI -->|synchronous\nreplication\nRPO zero| STB[Standby\nAZ-2]
    PRI -->|write ack only\nafter standby confirms| APP
    FAIL[Primary fails] -->|Route53 DNS\nupdates in 60s| STB
    STB -->|becomes new\nprimary| EP""",

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
    GP3[gp3 SSD\n3000 IOPS baseline\nscale to 16000] -->|Best value\nmost workloads| USE2[Production DBs]
    IO1[io1 Provisioned\nup to 256000 IOPS] -->|High throughput| USE3[OLTP\nhigh traffic]
    AUTO[Storage Autoscaling\ngrows when less than 10 pct free] --> GP3""",

    # Concept 4: Backups & PITR
    """flowchart TD
    PRI3[RDS Primary] -->|continuous\ntransaction logs| S3B[S3 Backup Storage]
    PRI3 -->|daily snapshot\nbackup window| SNAP[Automated Snapshot\n1-35 day retention]
    SNAP -->|manual copy| XSNAP[Cross-Region\nSnapshot for DR]
    S3B -->|point in time\nrestore to any second| NEW2[New RDS Instance\ndifferent endpoint]
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
    COST[NAT cost\n0.045 per hr\n0.045 per GB] -.-> NAT2""",

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
    EC2R[EC2 Instance] -->|AssumeRole via\ninstance metadata| STS2[STS\nSecurity Token Service]
    CICD[GitHub Actions] -->|OIDC token| STS2
    LAMBDA[Lambda Function] -->|AssumeRole auto| STS2
    STS2 -->|temp credentials\nkey + secret + token\n15min to 12hr| ROLE[IAM Role]
    ROLE -->|scoped permissions| S3R[S3 Access]
    ROLE -->|scoped permissions| DDBR[DynamoDB Access]
    TRUST[Trust Policy\nwho can assume] --> ROLE""",

    # Concept 3: Least Privilege & Permission Boundaries
    """flowchart TD
    MAXP[Maximum Permissions\nPermission Boundary] -->|hard ceiling| ROLE2[IAM Role]
    ROLE2 -->|attached policy\nmust be within boundary| EFF[Effective Permissions\nintersection of both]
    SEC[Security Team\nsets boundary] --> MAXP
    DEV[Developer\nsets role policy] --> ROLE2
    EFF -->|least privilege| ACCESS[Actual Access Granted]
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
    INIT -->|100ms to 1s\nadded latency| HANDLER[Handler runs]
    REQ4[Next Invocation\nwithin 15min] -->|warm reuse| HANDLER
    HANDLER --> RESP[Response]
    PC[Provisioned Concurrency\npre-warmed] -->|zero cold start\ncosts when idle| HANDLER
    SNAP2[SnapStart\nJava only\n90 pct faster] --> INIT""",

    # Concept 2: Concurrency & Throttling
    """flowchart TD
    REQS[1000+ requests\nsimultaneous] --> LIMIT[Account Limit\n1000 concurrent\nper region]
    LIMIT -->|within limit| EXEC[Concurrent Executions]
    LIMIT -->|over limit| THROTTLE[429 TooManyRequests]
    RC[Reserved Concurrency\nfunction cap] -->|protect downstream| EXEC
    PROVCON[Provisioned Concurrency\npre-initialized| EXEC
    THROTTLE -->|async invocations| RETRY[Retry with backoff\nthen DLQ]""",

    # Concept 3: Event Source Mappings
    """flowchart LR
    SYNC[Synchronous\nAPI GW or ALB] -->|caller waits\nfor response| LAMBDA2[Lambda]
    ASYNC[Asynchronous\nS3 or SNS or EventBridge] -->|queued internally\ncaller gets 202| LAMBDA2
    STREAM[Stream Polling\nSQS or Kinesis\nor DDB Streams] -->|event source mapping\nbatch processing| LAMBDA2
    LAMBDA2 --> SUCCESS[Success\ndelete from queue]
    LAMBDA2 -->|failure after retries| DLQ2[Dead Letter Queue]""",

    # Concept 4: VPC & Layers
    """flowchart TD
    LAMBDA3[Lambda Function] -->|VPC mode| ENI[Hyperplane ENI\nprivate subnet]
    ENI --> RDS2[RDS in\nprivate subnet]
    ENI --> REDIS[ElastiCache\nRedis]
    LAYER1[Layer 1\nnumpy or pandas] --> LAMBDA3
    LAYER2[Layer 2\ncustom runtime] --> LAMBDA3
    LAMBDA3 -->|max 5 layers\n250MB total| LIMIT2[250MB limit]
    TMP[tmp storage\n512MB to 10GB] --> LAMBDA3""",
],

}  # end CONCEPT_DIAGRAMS


def get_lesson(topic):
    """Return pre-written lesson for the topic, or None if not found."""
    topic_lower = topic.lower()
    for key, lesson in LESSONS.items():
        if key in topic_lower:
            return lesson
    return None


def get_concept_diagrams(topic):
    """Return list of 4 concept diagrams for the topic, or empty list."""
    topic_lower = topic.lower()
    for key, diagrams in CONCEPT_DIAGRAMS.items():
        if key in topic_lower:
            return diagrams
    return []
