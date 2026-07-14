# PDF 表格版面修復

以下表格依原 PDF 的頁面座標抽取，保留欄位位置；跨頁續表已合併。

## Table 1（PDF 第 3 頁）

*Adoption factors for OSS (adapted from Sa´nchez et al., 2020).*

```tsv
Adoption factors when	Technology		Organisation	Environment – not included in
				S´anchez
considering OSS choice				et al. (2020)
	Technological attributes	Economic (separate from technology in
		S´anchez
		et al., 2020)
Factors (# of papers citing	• Compatibility (34 papers	• Total cost of ownership (19)	• Support (45)	• Regulatory pressures
factor)	cited this factor)
	• Reliability (23)	• Licences cost (16)	• Training (25)	• Political pressures
	• Usability (17)	• Operational cost (4)	• Vendor lock-ins (13)	• Political and public pressures
	• Documentation (12)	• Support cost (2)	• Top management support	• Sustainability of open-source
			(10)	community
	• Maintainability (12)		• Attitude towards change	• Expertise in relevant open-source
			(6)	community
	• Reusability (8)		• Centrality of IT (3)	• Labour market for relevant skills
	• Portability (6)		• Case studies of FLOSS	• Market trends and industry
			adoption (2)	context
			• Time [to] adoption (2)
			• Business process
			reengineering (1)
```

## Table 2（PDF 第 4 頁）

*Participant and agency backgrounds (randomly sorted after country).*

```tsv
Country	Level	Type of Agency	Role with AI adoption
	Federal	Central and/or digital	Oversaw AI approach
	State	Delivery or regulatory	Led delivery of AI projects
	State	Central and/or digital	Oversaw AI approach
	Federal	Central and/or digital	Led delivery of AI projects
	Federal	Delivery or regulatory	Responsible for AI and data area
Australia
	State	Central and/or digital	Oversaw AI approach
	State	Delivery or regulatory	Led delivery of AI projects
	State	Central and/or digital	Responsible for AI and data area
	Federal	Delivery or regulatory	Responsible for AI and data area
	9 participants
	Federal	Central and/or digital	Led delivery of AI projects
	Province	Central and/or digital	Responsible for AI and data area
	Federal	Central and/or digital	Oversaw AI approach
	Province	Central and/or digital	Oversaw AI approach
	Province	Delivery or regulatory	Led delivery of AI projects
Canada	Federal	Delivery or regulatory	Oversaw AI approach
	Federal	Delivery or regulatory	Oversaw AI approach
	Province	Delivery or regulatory	Led delivery of AI projects
	Federal	Central and/or digital	Oversaw AI approach
	Federal	Delivery or regulatory	Responsible for AI and data area
	10 participants
	Federal	Delivery or regulatory	Responsible for AI and data area
	State	Central and/or digital	Responsible for AI and data area
	Federal	Central and/or digital	Oversaw AI approach
	State	Central and/or digital	Responsible for AI and data area
	Federal	Delivery or regulatory	Led delivery of AI projects
	Federal	Central and/or digital	Responsible for AI and data area
Germany	State	Delivery or regulatory	Oversaw AI approach
	Federal	Delivery or regulatory	Responsible for AI and data area
	Federal	Central and/or digital	Oversaw AI approach
	State	Central and/or digital	Led delivery of AI projects
	State	Central and/or digital	Oversaw AI approach
	Federal	Central and/or digital	Responsible for AI and data area
	12 participants
Total	31 participants
```

## Table 3（PDF 第 5 頁）

*Themes used in coding and frequency in coding.*

```tsv
TOE dimensions	Deductive themes from the	Inductive themes that
	literature	arose primarily through
		interviews
	Ordered by code frequency,	the % represents the share of
	the 31 participants where this	theme was coded
Technological	• Ongoing costs (54 times	• Tuning, post-training,
adoption factors	coded during thematic	prompt-engineering and
(31% of total code	coding, for 71% of	other AI tuning techniques
count)	participants)	(31, 45%)
	• Performance (47, 65%)	• Data maturity (20, 35%)
	• Upfront costs (36, 65%)	• Flexibility (5, 13%)
	• Ease of implementation
	(33, 65%)
	• Physical infrastructure
	(31, 71%)
	• Product fit (31, 68%)
	• Fit with existing tech-
	stack (28, 58%)
	• Innovation (19, 35%)
	• Cloud (18, 45%)
	• Debugging and useability
	(13, 35%)
	• Linked data (12, 29%)
	• Licensing (10, 23%)
Organisational	• Decision-maker support	• Procurement teams (45,
adoption factors	or influence (73, 81%)	68%)
(57% of total code	• Security (57, 77%)	• Digital sovereignty (42,
count)		71%)
	• Staff capability (51,	• Inter-Agency
	81%)	collaboration (42, 48%)
	• Policies (49, 68%)	• Role of the central
		(federal) government (20,
		45%)
	• Lock-in (46, 68%)	• Privacy and IP protection
		(18, 42%)
	• Organisational technical	• Administrative effects of
	sophistication (45, 65%)	AI (16, 42%)
	• Organisational attitude	• Transparency (15, 26%)
	towards OSS (41, 71%)
	• Culture (30, 52%)	• In-the-loop and
		guardrails (14, 23%)
	• Team attitude towards	• Fairness (9, 23%)
	OSS (31, 58%)
	• Resources and guidance	• Accountability (6, 16%)
	(28, 58%)
	• Regulation (18, 42%)
	• Team technical
	sophistication (9, 16%)
	• IT team (7, 19%)
Environmental	• Open-source community	• Internal support (e.g.
adoption factors	(38, 58%)	internal consulting, shared
(12% of total code		services) (26, 45%)
count)	• Competition (28, 48%)	• Academic support (10,
		19%)
	• Vendor or tech firm	• Reputation and brand (7,
	support (23, 55%)	13%)
	• Consulting support (21,
	39%)
```

## Table 4（PDF 第 8, 9 頁）

*Summary of differences in decision dynamics between traditional software and AI and across the study countries.*

```tsv
Dimensions	Differences in decision	Comparisons across the three
	dynamics for traditional	study countries
	software compared with AI
Technological	• AI models were seen to be	• Australian and Canadian
differences	more homogenous than	Agencies were more likely to
	traditional software, and	be using OSAI within a
	easier to benchmark and	proprietary cloud
	switch between, making	environment (e.g. Azure,
	trialling multiple models at	AWS) as they had taken up
	once feasible	Microsoft more extensively in
	• The definition of open-	the administration, while for
	source is less clear for AI than	regulatory, economic and
	for traditional software,	cultural reasons, German
	potentially weakening support	Agencies were mostly using
	for OSAI adoption by making	or seeking to use on-premises
	benefits more opaque	hardware
	• Cost concerns relate to the	• Data maturity was less of a
	need to invest in hardware	concern in Germany than
	infrastructure for open-source	Australia or Canada, perhaps
	AI and cost per token for	because the German Agencies
	proprietary AI, rather than the	had not progressed as far in
	largely upfront costs of	applying AI to wider datasets
	software implementation with	and are still in experimental
	OSS	stages
	• Fit and control of AI models	• Licences were a factor
	were more important than	mainly for German Agencies
	software usability	• Technological themes were
		proportionally cited across
		the three countries
Organisational	• The homogeneity of AI	• Staffing considerations
differences	models and relative ease of	driven by raw demographics
	switching means lock-in is less	are more predominant in
	of a concern – but Agencies	Germany, verses specific skill
	are already defaulting into	shortages in Australia and
	certain ‘easy’ choices, e.g.	Canada
	Copilot take-up
	• Considerations of digital	• With threats to Canadian
	sovereignty, privacy and data	sovereignty, participants
	protection, fairness,	there perceived that there
	transparency are more	had been a sudden spark into
	relevant for AI than	rethinking reliance on
	traditional software,	American cloud and platform
	particularly as how AI training	infrastructure to practically
	data has been sourced has	reduce dependence. This is
	been widely contested in	different from the more
	society. However, what data	historical view of digital
	were used to train the model	sovereignty that is
	was not a major factor in AI	predominant in Germany (as
	model choice, perhaps	reflected lower uptake of the
	because there is ambiguity	cloud there), while
	over the data OSAI models	Australian ones seemed
	were trained on	relatively less under pressure
		to reduce reliance on
		Microsoft and AWS
		infrastructure
	• Cultural attitudes around AI	• Internal IT and
	are evolving, meaning that	procurement teams within
	there is variability in openness	Agencies are more influential
	to experimentation across	in decision-making in
	Agencies	Australia and Canada, while
	• IT teams are more prominent	external government
	in the traditional software	Agencies (e.g. ITZ Bund,
	choice, while procurement	ZenDIS) are more influential
	teams are more so in the AI	in Germany. The larger
	choice	capacity of these German
		Agencies means they're more
		able to assist with in-sourcing
		and development
		• Organisational themes were
		slightly more frequently cited
		by Canadians and less by
		Australians
Environmental	• Less mature central	• German Agencies are more
differences	government guidance for AI	engaged with open-source
[continued]
Dimensions	Differences in decision	Comparisons across the three
	dynamics for traditional	study countries
	software compared with AI
	choice, while architecture and	communities compared with
	standards are established and	Canadian and Australian
	perhaps even stale for	ones, driven by regulation
	traditional software choice	and encouragement at a
		federal level
	• Open-source communities	• Inter-Agency and inter-
	and external supports are a	governmental collaboration
	critical factor for OSS, while	is stronger in Germany (80%
	being currently less relevant	of codes for collaboration)
	for whether OSAI is chosen,	than in Canada and Australia,
	given maintenance and	as well as the role of the
	substantial re-training of high-	federal government (70% of
	compute AI models is not	codes)
	feasible for a de-centralised
	community
	• Strong competition and high	• The roles of consulting,
	training costs mean	academic and internal
	developers of OSAI models	supports were somewhat
	retain more control over	more frequently coded for
	foundation models than OSS,	Australians than Canadians
	for example, not disclosing	or Germans, reflecting a
	training data and not	greater openness to bringing
	guaranteeing ongoing	in expertise from outside
	currency of the models	government
```

## Table 5（PDF 第 10 頁）

*Spectrum of open-source AI.*

```tsv
Model	Unrestricted open-source model	Restricted licence or ‘open-	Restricted technical	Restricted product access	A closed product
taxonomy		weight’	components
Key features	Involves: (1) model freely	Unrestricted open-source model	Unrestricted open-source	Access through an Application	User access solely
	available to download, (2)	except: (1) restrictive licence	model except: (1) model	Programming Interface (API)	through the provider's
	technical architecture and model	conditions, such as Meta's on	weights are not available	with limited opportunities to	product, with no way
	weights publicly open, (3) no	certain commercial use or	publicly, (2) in most cases,	fine-tune, however, can be	to access it outside of
	licence or widely used,	distillation, or (2) a customised	a restrictive licence as well	incorporated into a third-party	their ecosystem
	unrestrictive licence (e.g. MIT or	licensing agreement		product
	Apache 2.0)
Prominent	Most Mistral AI models, OpenAI's	Meta's Llama models,	AlphaFold models, Baidu's	Most of OpenAI's GPT models,	Amazon's Alexa,
examples	GPT-OSS models, DeepSeek's R1	Alphabet's Gemma models,	Ernie model	most of Alphabet's Gemini	Microsoft's Copilot,
(as of late-	model, TTI Falcon models,	DeepSeek's V series models		models, Anthropic's Claude	Apple's Siri
2025)	Databricks's Dolly model			models
```

## Table 6（PDF 第 10, 11 頁）

*Key differences between OSAI and OSS.*

```tsv
Aspects	OSAI	OSS
Technical	> Conceived and developed by a foundation model developer, generally a formal	> May be conceived by a single person, community or company and
development	company thus far	then published on a code sharing platform like GitHub
	> Training the AI model requires access to high quality data and substantial hardware	> No specific capital required to develop deterministic software code
	infrastructure
Access	> Many models considered OSAI are strictly open-weight models with a restricted	> Much of OSS is code that can be simply copied from the source
	licence conditions	repository
	> Can also be accessed through an API endpoint on a cloud platform	> In most cases with unrestrictive licences, OSS may be seamlessly
	> On-premises deployment generally involves downloading the model files	incorporated into other traditional software, including proprietary
	> OSAI models cannot be as easily analysed and assessed as OSS	software
[continued]
Aspects	OSAI	OSS
Adaption of the	> For those models whose model weights are not published, the model is to some	> Users can suggest changes to core codebase and contribute their
tool	extent, still a black box	own changes or improvements
	> Users can fine-tune their own forked versions of the model but the fundamental	> OSS can be easily forked and completely revamped by a user
	model is difficult to significantly modify without re-training due to the data processing
	capacity (either on-prem or in the cloud) required
```
