# Open to open-source AI? Navigating AI model choice in public sector agencies

Contents lists available at ScienceDirect
Government Information Quarterly
journal homepage: www.elsevier.com/locate/govinf
Open to open-source AI? Navigating AI model choice in public
sector agencies
Nicholas Robinson*
Hertie School of Governance, Germany

A R T I C L E I N F O
Keywords:
Artificial intelligence (AI)
Public sector AI adoption
Open-source
Digital sovereignty
Technology-organisation-environment
framework

A B S T R A C T
Public sector Agencies are increasingly adopting artificial intelligence (AI) tools. High quality open-source AI
(OSAI) options are available, but much of their current attention is on proprietary options such as Copilot and
ChatGPT. There are parallels with take-up of open-source software (OSS). While OSS has a foothold in niche
functions of Agencies' technology suites, it has not seen widespread adoption despite backing from technical and
political spheres and its potential to reduce costs and spur increased competition and innovation.
Grounded in theoretical frameworks and evidence used to investigate OSS uptake, the study draws on interviews with 31 decision-makers on AI adoption in Australian, Canadian and German public sector Agencies to
analyse key factors in the feasibility of open-source technologies in general and OSAI in particular, compared to
their proprietary counterparts.
In comparison to determinants of OSS adoption, technological characteristics like fit, control and the availability of hardware infrastructure are more influential in whether OSAI is adopted. Furthermore, organisational
considerations like digital sovereignty and data protection were more prominent in the AI decisions. Conversely,
AI models are more homogenous and easier to switch between than traditional software products, meaning that
perceptions of usability, fears of vendor lock-in and availability of support were not as strong an influence as with
OSS.
Although AI is a fast-evolving technology, the choice to adopt OSAI or proprietary AI involves making commitments today — like investment in hardware and building internal sovereign capabilities — that will echo into
the future.

1. Introduction
Decision-makers in public sector agencies (hereafter, ‘Agencies’1)
have long considered open-source software as an alternative to proprietary software, however, take-up varies across regions. With the
emergence of public sector artificial intelligence (AI) adoption, Agencies
are making similar assessments about the suitability of open-source AI
(OSAI) models compared with proprietary AI models.
Since 2022, significant public attention has been brought to AI
through the release of user-friendly tools such as ChatGPT, leveraging
technology advances in computing scale, model architecture, access to
large amounts of data and refinement in training techniques
(Brynjolfsson et al., 2023; Hjaltalin & Sigurdarson, 2024). Increasingly,
the advances and widespread uptake of AI tools have been largely seen

in proprietary AI models and products from American developers such
as OpenAI (GPT models), Alphabet (Gemini) and Anthropic (Claude)
(Burkhardt & Rieder, 2024; Tarkowski & Open Futures, 2025). Prominent OSAI models have come from more globally dispersed developers,
such as Meta (US), Mistral (France), Alibaba, Baidu and High-Flyer (all
based in China).
The definition of OSAI has been contested (Bateman et al., 2024;
Floridi et al., 2025; Liesenfeld & Dingemanse, 2024). In an OSS context,
scholars used characteristics such as costless access, a permissive
licence, a related community and full documentation (Rossi et al., 2012;
Sa´nchez et al., 2020; Shaikh, 2016). OSAI definitions contain additional
criteria such as accessible model weights and transparent model architecture, training methodology and training data (Bateman et al., 2024;
Bommasani et al., 2021; Tarkowski & Open Futures, 2025), however,

* Corresponding author at: Friedrichstrasse 180, 10117 Berlin, Germany.
E-mail address: n.robinson@phd.hertie-school.org.
1 Agencies is a term used in the Australian and Canadian contexts to capture the range of government organisations when referring to them collectively. It is used
in part to avoid using an acronym instead.
https://doi.org/10.1016/j.giq.2026.102133
Received 24 September 2025; Received in revised form 4 March 2026; Accepted 10 March 2026
Available online 20 March 2026
0740-624X/© 2026 The Author. Published by Elsevier Inc. This is an open access article under the CC BY license ( http://creativecommons.org/licenses/by/4.0/ ).

there is still a lack of consensus. Interview participants were not as
stringent about their classifications of OSAI. Somewhat restrictive
licence conditions imposed by developers like Meta and DeepSeek were
seen as relevant only to defence and security agencies. Furthermore, no
major AI model developer has fully disclosed the sources of its training
data (Tarkowski & Open Futures, 2025). As discussed further in Sections
4 and 5, such definitional ambiguity impacts Agencies' real-world
technical investment and procurement decisions, risk assessments and
efforts to strengthen sovereignty, by muddying which AI tools are
actually open-source. Different criteria of openness are covered in
further detail in Appendix 1. For the purposes of this analysis, OSAI
refers to AI models that are free to access, have generally unrestrictive
licence conditions and are accompanied by sufficient transparent information for Agencies to substantially customise them and make them
‘sovereign’, acknowledging that this definition includes some models
that are strictly seen as ‘open weight’ such as the Llama and Gemma
models, rather than maximally open-source models like EleutherAI's
Pythia series (Tarkowski & Open Futures, 2025; Widder et al., 2024).
Existing research on government's adoption of AI in the public
management and governance field has not kept up with novel technological advances (Haug et al., 2024). Both proprietary and open-source
AI models are fighting to be seen as the innovative choice (Azoulay et al.,
2024). Whether OSAI or proprietary models dominate governments' AI
take-up has flow-on impacts to digital sovereignty, cost structures for AI
investments and internal skills needs. Although OSAI is neither necessarily more or less innovative than proprietary options, it is seen as a
challenger to the status quo of proprietary AI, potentially enabling
differentiated improvements to products through a multi-stage process
of adoption (Baregheh et al., 2009). Despite public administrations'
stated support or even hype towards OSS (Freeman, 2012), there has
long been a preference towards proprietary options (Rossi et al., 2012).
OSS is on the one hand seen as more customisable, cost effective and
sovereign, but has perceived disadvantages such as worse usability,
being more challenging to technically and organisationally implement
and a lack of an actor responsible for maintaining it (ibid.; Shaikh, 2016;
Hauge et al., 2010; Sa´nchez et al., 2020). The evidence presented in this
study will indicate that proprietary AI is the current default for most
Agencies. Nonetheless, while innovation diffusion theory presents a
range of possible factors for successful adoption, it alone is not sufficient
to understand why OSAI is chosen over proprietary AI or vice versa. The
widely used Technology-Organisation-Environment (TOE) framework is
therefore deployed instead to structure the analysis. This study is guided
by two research questions viewed through a TOE lens:
Research question 1: What informs the choice of Agencies to adopt opensource software verses proprietary options?
Research question 2: Are the patterns of OSAI take-up in Agencies likely
to be different from OSS?
To address these questions, I draw upon the perspectives and experiences of 31 decision-makers on AI in Australian, Canadian and German
Agencies, via semi-structured interviews. I argue that the decision process for choosing between open-source and proprietary AI brings many
of the same considerations as for OSS verses proprietary software, in
particular on an organisational level, but that the technological and
environmental dimensions differ substantially. AI models function in a
more homogenous way than traditional software products but their
success is also more dependent on the surrounding technical ecosystem,
including Agencies' tech stack and data. The early stage of AI adoption
means that many of the environmental factors are still in flux; in
contrast, communities, supports and relevant regulations for OSS are
well-established, if not always positive factors.
In section 2, I cover the relevant theoretical background to OSS and
OSAI adoption. In section 3, I describe the research design for this
empirical study. Section 4includes findings from interviews and section
5 covers discussion and implications.

2. Theoretical background
2.1. Innovation adoption in the public sector
Adoption of new technologies in studies of innovation diffusion is
typically framed as a binary of a status quo and a new innovation, for
example, classical examples on whether hybrid corn or boiled water are
taken up or disregarded (Edquist & Hommen, 2000; Rogers, 2003; Ryan
& Gross, 1943). AI is the most recent major technological innovation to
be considered by governments.
To understand how innovations are taken up, scholars have deployed
theoretical frameworks such as the diffusion of innovation theory
(Rogers, 2003), the technology acceptance model (TAM) (Davis, 1989)
and its successors including the unified theory of acceptance and use of
technology (Venkatesh et al., 2003). These provide a wide range of
factors explaining why innovations will diffuse and be adopted. However, when choosing between two broadly substitutable new technology
choices however, the mechanisms described by these theories are less
suited. For this reason, I choose to inform the choice between
open-source and proprietary technology using factors from innovation
diffusion theories but subsume them into the Technology Organisation
Environment (TOE) framework. Tornatzky and Fleischer (1990) developed the TOE framework, arguing that the adoption decision was driven
by the attributes of the technology itself as well as organisational and
environmental contexts. Numerous subsequent scholars have taken this
approach, including while studying traditional software choices (e.g.
Sa´nchez et al., 2020; Ven & Verelst, 2006) as well as in AI adoption (e.g.
Chen et al., 2024; Madan & Ashok, 2023; Mikalef et al., 2022; Neumann
et al., 2024).
2.2. The choice between open-source and proprietary software
The decision whether to adopt traditional software from open-source
or proprietary sources has been widely studied in both a public
administration and private organisation context and is highly influenced
by ideological factors (e.g. Medappa & Srivastava, 2020; Stewart &
Gosain, 2006; Ven & Verelst, 2006). Here, the TAM makes an important
contribution by highlighting the role of decision-maker perception as
distinct from a fully objective reality. There do not appear to be neither
shining examples of functional fully open-source governments —
although the German state of Schleswig-Holstein is currently aiming in
this direction (Landesportal Schleswig-Holstein, 2025) — nor those who
are entirely content with being fully reliant on proprietary tools with
uncertain digital sovereignty implications. This reflects a complex
mixture of diffusion, acceptance and adoption factors. Broad studies
such as the systematic literature review by Hauge et al. (2010) found
that technology-focused reasons were the key factor behind the choice of
OSS over proprietary tools. Similarly, others claim with their free access
and ability to be customised, open-source options are seen as more independent, localised, cost-effective, flexible and specialised than proprietary ones (Bouras et al., 2014; Hauge et al., 2010; Ven & Verelst,
2006, Van Loon & Toshkov, 2015), with greater ability to satisfy user
needs, lower frequency of software bugs, strong security and freedom
(Bouras et al., 2014; Freeman, 2012; Gurusamy & Campbell, 2012;
Raymond, 2000). However, while the Belgian organisations studied by
Ven and Verelst (2006) cited features like richer documentation and
source code as valuable, none actually drew upon them. Furthermore,
despite its costless sticker price, a perception can conversely emerge that
this implies it is risky or low quality (Freeman, 2012; Noronha, 2002;
Shaikh, 2016).
The ease of use of proprietary options could explain why they are
prevalent across public administrations. Compared with proprietary
options, the flexibility of open-source tools can result in higher technical
complexity, requiring a steeper learning curve (Shaikh, 2016). A number
of studies report switching back from OSS to proprietary tools, even after
a period of attempted OSS adoption, which would indicate that the

product benefits were insufficient to overcome negative perceptions of
ease of use (e.g. Fitzgerald, 2009; Rossi et al., 2012; Shaikh, 2016).
Many studies find that organisational dynamics are critically important
to whether OSS is adopted (e.g. Holck et al., 2005; Shaikh, 2016; Zuliani
& Succi, 2004).
Whose opinion counts also matters. Many studies cite the role of
managers — as distinct from technical staff or executive leadership — as
a pivotal cohort in successful adoption (Freeman, 2012; Rossi et al.,
2012; S´anchez et al., 2020; Shaikh, 2016, Van Loon & Toshkov, 2015).
In her in-depth interviews, Shaikh (2016) found that managers preemptively change-course in anticipatory response to internal problems
that may occur with OSS adoption, from a steep learning curve to a
possible lack of support. Shaw (2011) found that OSS was promoted by
“insurgent experts” who expended political capital on its adoption. In
research on Finnish public sector adoption of OSS, Freeman (2012)
contrasted the pro-OSS views of technical staff with the pro-proprietary
software views of clerical staff. Workers who self-select to go into the
public service tend to have a more risk averse profile (Chang, 2024;
Schofield, 2001), perhaps influencing their perceptions of OSS's costbenefit trade-off as a challenger product compared to familiar proprietary software.
Leveraging external supports like consultancies or technology vendors is a key method organisations can use to improve perceptions of
open-source tools' ease of use. Many don't have sufficient internal
capability present to fully implement in-house (Shaikh, 2016; Van
Noordt & Tangi, 2023). As open-source tools are typically provided
without warranty, liability or guarantee, outsourcing some or all of the
implementation transfers the perceived responsibility for delivering a
useful product from the organisation itself to the external support (Holck
et al., 2005). If this support is no longer available, it can cause delays in
implementation (Shaikh, 2016). This dynamic is particularly distinct in
the choice between traditional software, as proprietary products may be
supported by the original vendor itself as well as consultancies with
relevant expertise. Agencies may find it reassuring that a brand sits
behind any new technology (Freeman, 2012; Shaikh, 2016). External
supports can extend to formalising the role of open-source communities.
Two of the five elements in Shaikh's (2016)definition of open-source —
community and coordinating mechanisms— are distinct from the technology itself but instead are reflect the ongoing support from the OSS
community.
In comparison to the wide range of research on OSS adoption, academic research on OSAI thus far has been mainly limited to how OSAI
models are technically developed (e.g. Osborne et al., 2024), definitional debates about what should be considered OSAI (e.g. Liesenfeld &
Dingemanse, 2024; Widder et al., 2024), geopolitical and corporate

competition (e.g. Floridi et al., 2025; Widder et al., 2024). The latter
issue points to digital sovereignty being a relevant adoption factor for
OSAI, in contrast with OSS take-up, where security was a stronger factor.
Adoption mechanisms related to community input and support are likely
to be also less relevant for OSAI, as foundation models are typically
sourced as a product directly from the original developer with minimal
guarantee of support, although as Shaikh (2016) points out, the ideal of
a collaborative and responsive repository supporting an OSS project is
not always realised in practice. This ‘productisation’ limits how an OSAI
model mutates over time, with models being superseded by the original
developer rather than upgraded.
In their SLR on Free / Libre / Open-Source Software (FLOSS) adoption across public and private sector organisations, Sa´nchez et al. (2020)
catalogued a wide range of adoption factors for OSS cited in the 54
papers they reviewed, as shown in Table 1. While they defined TOE's ‘E'
as Economic, Environmental adoption factors (those not in the control of
the organisation nor being key features of the technology) have been
added to align with the typical TOE formulation.
A challenge in reviewing the available literature is that much of the
empirical research on OSS adoption is framed as a search of reasons to
adopt OSS or focuses on success factors for OSS adoption, rather than an
equally-weighted evaluation of OSS verses proprietary software. For this
reason, the subsequent analysis will assume that proprietary software
and AI are the status quo and open-source alternatives are the challengers. This reflects real-world patterns of both traditional software and
AI, although open-source has notably been highly prevalent in pregenerative AI machine learning applications (Bright et al., 2025).
3. Research design
To address the research questions, this study primarily draws upon
31 semi-structured interviews with current or recently formerly
employed decision-makers in public sector Agencies in Australia, Canada and Germany conducted in December 2024 and the first half of
2025. Initial literature review and desktop research indicated that there
was scarce research on AI model choice in the public sector, particularly
relating to OSAI. This informed the choice of relying on interviews
instead of case studies for data collection, with the advantage of
capturing a wider sample of viewpoints and considerations. Further
research using case studies may help to explore the themes raised in
more depth. In addition, to inform the interview guide (shown in Appendix 2) and provide a timely overview of the status quo, contextual
information on AI model features and implementations was drawn upon
from sources such as model developer websites, user forums and media
reporting.

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

Source: Adapted from S´anchez et al. (2020). Environmental adoption factors synthesised from Shaikh (2016), Ven and Verelst (2006), Badampudi et al. (2018),
Dedrick and West (2004), Munoz-Cornejo et al. (2008), Freeman (2012).

3.1. Recruitment of participants
Participants were identified using documentary evidence collection
on government AI initiatives, personal outreach via email or LinkedIn
and recommendations from other participants — a snowball sampling
technique practiced by others including Freeman (2012). The participants were approximately one-third women and two-thirds men.
The choice of Australian, Canadian and German jurisdictions was
driven by several factors, including:
• availability and openness of senior decision-makers to be
interviewed;
• the federal structure increasing the number of decision-makers
compared to centralised states, due to higher autonomy for states
or provinces, and providing greater heterogeneity across
perspectives;
• avoiding jurisdictions with globally prominent home-grown models,
which may bias decision-making;
• a relatively advanced consideration of AI implementation choices (if
not broad implementation) as these jurisdictions tend to have more
insights on AI adoption, following the example of Van Noordt and
Tangi (2023).
The breakdown of participants and their Agencies is shown in

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

Notes: (1) Generalising the role is important to maintain anonymity as the
number of the AI decision-makers is still relatively small. (2) In a German
context, the state level includes cities. (3) The roles are defined as following:
‘Responsible for AI and data area’ means the participant was the leader of this
function or department, ‘Oversaw AI approach’ means that the participant had a
role overseeing, determining or coordinating AI projects without necessarily
being a departmental leader, ‘Led delivery of AI projects’ means that the
participant held senior technical or delivery responsibilities.

Table 2:
The key inclusion requirement for participants was proximity to or
influence over the decision-making process on AI model choice,
following the example of Gurusamy and Campbell's (2012) selection of
public servants who influence the decision to adopt OSS. In practice,
participants fit into one of three categories: responsible for an AI function or department, having an oversight role on AI adoption or technical
leader of AI projects. Although the scope of public sector AI adoption is
expanding, according to participants themselves, the population of
decision-influencers on the choice of AI model is relatively small across
the three jurisdictions, particularly at a federal level. Thus the 31 participants come from most of the key Agencies with influence on AI
adoption in each jurisdiction, representing a relatively a strong sample
of relevant contemporary perspectives and experiences. Further sampling would enable more quantitative analysis but is likely to echo the
standpoints shared in this study.
To allow candid insights, participants participated in their personal
capacities drawing on their experiences in respective Agencies, rather
than representing any official positions. De-identification of participant
names, positions and specific Agencies was important for two main
reasons. First, to ensure participants could speak critically of their own
Agency's culture and decision-making (even if not all did), and second,
on probity grounds, to avoid prejudicing current active procurements of
AI models, including with vendors mentioned in the study.
3.2. Data collection
The interviews were all conducted via video-conference through
Microsoft Teams for between 45 and 90 min and semi-structured using
contextual and thematic questions developed using previous research on
OSS choice, theories of innovation adoption and framed using TOE. The
interview guide is shown in Appendix 2. To minimise any biasing discussion of AI adoption towards open-source, contextual data on AI
implementation was gathered before discussing open-source vs. proprietary choice, before returning to decision-making and enabling
factors.
The German interviews were conducted by the author and an additional fully fluent German speaker to ensure fine nuances of language
were not missed in the interaction. The questions were structured into
the following categories from early discovery to acceptance and implementation: Context and background, AI initiation and implementation,
consideration of open-source, decision-making process and influences,
and enablers and flow-on effects. The interview was conducted using
mainly open questions, meaning that some participants chose to focus
more on technical factors and others on organisational ones. Participant
responses were de-identified using country code (e.g. AU7, CA4, DE4)
with the number chosen at random. Participants were asked whether
there were supplementary sources of information that should be referred
to, e.g. policies and guidance. Almost no participants cited any sources
generated by government, therefore documentary evidence was not a
significant source of further data. The lack of guiding materials is discussed further in Section 4.
3.3. Data analysis
Interview transcripts were captured in almost all interviews except
two, which proceeded using closely captured manual notes at the participants' request. Transcripts in German were translated to English
using the Microsoft Translate tool and checked by the author. The quotes
used in Section 4 are as literal as possible. All identifying proper nouns
have been removed and in the case of three participants, quotes have
been slightly summarised for additional anonymisation.
Processed interview transcripts were coded using a form of qualitative content analysis that aims to extend existing theory, which Hsieh
and Shannon (2005)term directed content analysis. This approach relies
on open-ended questions that aim to avoid priming participants to

follow a certain direction. That the data analysis is ‘directed’ initially by
the deductive themes sets it up for later comparison between the previous and current state, as is the goal of the Research Questions. The
approach taken here also includes abductive elements as it is actively
open to new themes (Timmermans & Tavory, 2012) to engage with AIspecific dynamics. The code book (see Appendix 2) drew on deductive
themes from literature on OSS adoption covered in Section 2 as well as
research on AI adoption (for example, Mergel et al., 2023; Neumann
et al., 2024; Pumplun et al., 2019; Straub et al., 2023; Van Noordt &
Tangi, 2023; Wirtz et al., 2019) to obtain guide AI-specific themes.
To ensure the context was fresh and allow for a code-recode
approach (Fusch & Ness, 2015), initial coding was undertaken immediately after each interview (generally within a few days) using deductive themes derived from literature as well as inductive themes. The
process of coding involved marking identified themes but also making
notes and clarifications alongside for further refinement. The TOE
framework helped structure the coding. Later, a few weeks after the last
interviews, the transcripts (and manually captured notes) were placed in
a consolidated document where a further round of coding took place to
check deductive themes as well as code new inductive themes into
earlier interviews and clarify their definitions. Over time, the themes
were tracked using the spreadsheet to record definitional changes,
necessary exclusions, inclusions and examples and monitor the emergence of new themes. Saturation was indicated when the identified
themes comprehensively accounted for the data, as indicated by low
incremental learning (Eisenhardt, 1989), for example, no new themes
emerging, which occurred after the second coding cycle. Table 3 shows
the deductive and inductive themes identified as well as respective
frequency counts and the share of participants where the theme was
coded.
Using the coded transcripts, quotes or paragraphs were categorised
into a separate, thematically-structured document in order to de-link
them from individual participants' transcripts and capture a more holistic sense of each theme. This document was used to undertake further
inductive analysis, as well as checking the deductive coding against upto-date theme definitions, prior to a final phase to check codes, where
saturation was confirmed. The thematic document also helped to highlight relationships between adoption factors across participants and
countries. These links which are discussed further in Section 4. Definitions of codes used in thematic analysis are shown in Appendix 3.
In interpreting the following analysis, it is important to note that the
AI adoption was rapidly evolving in Agencies in the study period. During
data collection, DeepSeek was released and Canada received stated
threats to its sovereignty. Both impacted the decision-making on AI
model choice, adding a future-looking perspective.
4. Findings
The following sub-sections are organised to sequentially answer RQ1
and RQ2 structured using the TOE framework.
4.1. What informs the choice of Agencies to adopt open-source software
verses proprietary options?
4.1.1. Technological dimension
Although interviews focused primarily on the consideration of proprietary vs. open-source AI, participants often addressed this choice by
reflecting on open-source technologies in general. Their perception of
Agencies' stance to open-source differed based on its fit with the existing
technology stack. A key barrier to open-source adoption was that it requires Agencies to have invested more in their own infrastructure, for
example, on-premises servers, CPUs and GPUs. In contrast, hosting and
processing of proprietary software is typically managed by the vendor.
According to AU1, “there's probably been a significant under-investment [in
our own infrastructure] for a long time”. Proprietary options have been
more attractive to Agencies, if they “forgot how to pay technical debt … I

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

Notes: (1) Each code assignment was counted individually. Individual codes
could be used more than once for each interview transcript, however, care was
taken to ensure that a code was only used again when the subsequent instance
was distinct of previous instances by contributing a different insight to previous
instances. (2) The frequency counts and percentages may be affected by the
composition of the sample across the three study countries, although the number
of participants were reasonably balanced across the three countries.

Australian and Canadian Agencies appeared to be much more reliant on
the cloud, making up nearly 80% of times coded. Factors relating to fit,
compatibility and ease of implementation were strong but not predominant themes, echoing previous OSS literature (see Table 1).
4.1.2. Organisational dimension
With over half of all theme frequency counts relating to the organisational dimension, these factors were more prevalent in whether opensource was considered feasible compared to proprietary options. Fourfifths of participants saw staff capability as a significant factor, with
lower internal capacity making it more difficult to undertake the more
intensive technical work needed to adopt open-source options, as noted
by Shaikh (2016), Sa´nchez et al. (2020) and Rossi et al. (2012).
Australian and Canadian Agencies were concerned with the right mix of
skills, for example, “we have some skills gaps in a lot of our product teams”
[CA9], particularly around DevOps, data engineering and AI engineering. AU8 blamed the issue of skills on the “the presumption that expertise
which includes technology is an externalisable commodity that whenever you
need it, you can just buy”. In comparison, German Agencies appeared to
be generally stretched, with a several simply citing reasons like “a crazy
shortage of skilled workers [in the wider economy]” [DE12] or “demographic
change” [DE4] as a reason why building in-house can be more risky.
Perhaps for this reason, a large majority of them brought up an advantage of open-source of being to collaborate and leverage economies of
scale across many Agencies and even other countries in Europe. This
reflects a far greater perceived organisational openness to open-source,
with German participants much more likely to bring up broader history
and context of open-source outside of an AI context. However, DE11
viewed skill shortages as a straw man for a higher-level issue: “there is no
need for more open-source developers, it is the decision-makers who need to
change tack”. DE6 pithily summed up the attitudes of some decisionmakers: “in the view of the department head, open-source was something
we used to program at university when we came home after three beers”.
Almost all participants personally supported open-source, like CA9: “we
had a very strong bias towards open-source solutions over the last 5-6 years”,
but also cited the suspicions of other decision-makers as constraining
factors, e.g.: “they would much prefer to deal with a known vendor and buy
an off-the-shelf product” [AU1] or that it “started to become associated as
the things that well-meaning hippies do” [CA4].
A key hurdle for open-source options is at the procurement stage,
where the “lack of Service Level Agreements” [DE11], “procurement systems
are geared towards incumbency and big vendors” [AU4] and that it's hard to
explain that they're “procuring something that someone else can use later”
[DE8] make ticking compliance boxes for open-source difficult. In part
these can stem from security or integrity concerns: “with open-source,
there was always a perception that the Chinese or Russians are in it”
[DE8] although others viewed its openness as an advantage: “opensource tools can be very secure given they've been looked at by many, many
people often” [CA2]. Furthermore, in the view of AU8, “the point with
open-source is, it doesn't matter when it's come from, you can actually assure
it”, an increasingly significant factor when “[the government is] essentially
giving Microsoft a very privileged view of what happens inside” [CA4] and
“we'll see something like Zelensky and Trump [February 2025 meeting in the
Oval Office] on a German level in 10-20 years if we've moved the whole
administration to Azure” [DE4]. These concerns were shaking the lock-in
of some proprietary providers perceived by participants: “Microsoft have
a head agreement with the government … so that puts them in quite an advantageous position” [AU5] and “the least amount of friction is the Microsoft
way … you arrive, your computer is pre-loaded with it … for everything else is
a path of approvals” [CA4].
4.1.3. Environmental dimension
Increasingly, external factors are driving decision-making. Germany's Onlinezugangsgesetzes (OZG) was perceived by DE11 as essentially mandating software be open-source in some circumstances.
German participants made up 70% of times the role of the federal

government was coded, reflecting far greater enthusiasm for central
coordination and leadership. For instance DE3 “recommend[ed] having a
central unit available as a contact point on open-source” and DE10 hoped
“there will be new structures in the federal government”. This reflects the
tension between Germany's “decentralised federation” [DE11] with a
desire for top-down guidance and rules on when open-source is suitable
compared with proprietary. DE12 thought government should “think
more European” and CA10 documented a need to “interoperate with [other
allied countries]”. Many participants viewed government as taking opensource communities for granted, e.g. “we have to get rid of this fallacy that
the wider community is just going to develop things for us” [DE5], however
others, primarily in Australia and Canada, warned that it was not realistic for government to become a wide-scale contributor: “if I've got my
team spending 100 per cent of their time contributing to open-source projects,
that's also not a great use of taxpayer dollar” [AU7]. Highly capable
external consultants were seen as relatively neutral towards opensource, “vendors will try more or less to give you what you asked for”
[AU6], although some “want to sell us closed systems because that's how
they lock us in” [DE4]. Much of the concern about open-source adoption
comes back to relative brand weakness, with a number of participants
citing the adage that “no one ever gets in trouble when you use IBM” [CA2]
or a variation thereof that substitutes Microsoft. AU4 highlighted the
importance of “social licence” for government as a reason for trusting
established brands, although reputation was not a widely mentioned
factor amongst participants.
4.2. Are the patterns of OSAI take-up in Agencies likely to be different
from OSS?
4.2.1. Context of AI adoption
To ground the analysis of OSAI take-up, it is useful to understand
how Agencies are seeking to adopt AI. Productivity use cases (e.g.
summarisation, knowledge management) were the most common, represented in nearly half of use cases cited, followed by operational deployments (built into a process, e.g. anomaly detection, prediction or
document generation) with around a third, followed by customer-facing
cases and regulatory cases.2Given their responsibilities for AI adoption,
participants did not express as much scepticism about its potential as in
wider societal discourse, however, nonetheless identified weaknesses in
current model capabilities.
4.2.2. Technological dimension
Although open-source AI has a long history in government, the
confusion about AI verses machine learning and prominence of the debates around whether models like Llama are open-source means that
participants generally anchored on generative AI when discussing OSAI
verses proprietary AI. A key difference between pre-generative OSAI and
generative OSAI is that the dependence of the latter on the company that
trained the original foundation model is much more significant due to
the high cost of model training. Participants could fine-tune but not
fundamentally change the nature of an OSAI model. However, in comparison to the often sharp distinctions between proprietary and OSS
products, there are small perceived differences in functionality, performance and accuracy across most prominent AI models. AU7 commented
that, “[accessing] commoditised LLMs through existing commercial and
support arrangements makes sense, like we're not going to go out and replicate
what is automatically available.” CA8 referenced the 2023 Google paper
that stated that they had “no moat”. For specialised, non-LLM use cases
such as AU2's, more effort was expended looking at accuracy. Other
Agencies used indicators such as popularity on Hugging Face [CA2,
DE6], side-by-side comparisons of model outputs or external analysis
2 The categories of AI deployment are not mutually exclusive. Further
research on how governments are deploying AI tools would enhance the context
of overall adoption.

and media reporting to gauge which performed best. This differs from
OSS where software is seen as harder to benchmark. Nonetheless, like
OSS, usability was highly important, although participants referred
instead to concepts like fit, flexibility and control of an AI model, e.g.
“you can actually take open-source models and make them right for your use
case” [AU6]. This linked to data maturity, a key factor in deciding
whether to choose open-source or proprietary. Not only “data governance” [AU1, CA9, CA7] but “that data today is very siloed” [CA2]. AU4
summed up the challenge: “if information management is terrible, then AI is
just going to amplify it”. However, even with high quality data, processing
them in-house is dependent on variable infrastructure readiness across
Agencies in all three countries, a theme raised by a large majority of
participants. Some “have already the mature infrastructure that allows them
to leverage tools like this” [CA5] and some still catching up or reluctant to
“support our own hardware” [AU5]. While this dynamic is similar to OSS,
it is more acute for AI because data processing requirements are so much
higher: “our standard data centres are not designed for such a high energy
requirement per cabinet that AI generates. So maybe some Agencies are going
for commercial models because they don't need to deal with that” [DE5].
Infrastructure suitability was not the only barrier, but also the ability to
access or invest in it. While DE8 cited a very large GPU concentration
available to the Agency, it was apparently “not reliable, often crash[ed]
and then sits idle for another two days”, similarly DE6: “we have the
hardware and software resources to build something in-house … it's more a
question of operability and maintainability”. Others however, could not
easily access hardware as it “involves very high investment costs” [DE1].
Australia and Canada were more focused on cloud — where both proprietary and OSAI models can be deployed. This paradigm involved its
own cost considerations, e.g. “if your scale is quite small and the number of
transactions you're going to have with an AI system are going to be relatively
low — paying for a proprietary access to AI is not particularly expensive …
whereas if you're rolling out genAI systems to [thousands of people in a large
Agency] that were going to hit them every day … that would get extremely
expensive” [AU6]. There was concern that the trade-off was yet to be
settled: “the costing models [are] changing quite a lot” [CA5], “the cost for
these [proprietary] models are as cheap as they'll ever be today” [CA3] and
“even if you choose an open source model and bring it to a public cloud
platform, you're paying to store it” [CA1].
4.2.3. Organisational dimension
The organisational influences on AI model choice strongly related to
cultural and attitudinal factors regarding OSS but also interacted with
the general discourse around AI. The low technical knowledge of senior
management in Agencies was seen as contributing to a cautious attitude
towards AI, in particular less familiar ones. Microsoft Copilot was seen
by many as the safe, default option: “we're gonna sign onto Microsoft
Copilot 365 and then that's the only tool that you will use” [CA6]. Participants described the attitudes of senior executives towards exploration of
new AI options as “scared” [AU1], “play it safe” [CA3], “lacking [AI] literacy” [AU1], having “breathless risk aversion” [CA7]. However, CA2,
CA7 and AU5 recounted how senior management learning about AI or
coming up with ideas of AI use cases had helped spur greater openness to
new forms. DE3 documented how it took two years for the Agency to
become comfortable with Python (a programming language with
numerous open-source packages), requiring “throw[ing] the decisionmakers very simple treats for them to make rather uncomfortable decisions”. Adoption of OSAI — and other innovative AI uses — was more
likely to be chosen when small technical teams (termed “skunkworks” by
AU3) had primary decision-making responsibility and autonomy in a
“sandbox” [AU1], in many cases falling below the monetary thresholds
that required more compliance.
In addition, the relative novelty of AI means that incumbent vendors
with strong AI offerings are benefiting from procurement practices that
favour continuity, for instance, “where companies offer certain AI systems
… it's quick, we just buy licences” [DE6]. However, lock-in was far less of
an issue for AI models than with traditional software: “We try to keep

flexibility, we now have in our framework [that] we can also exchange
Mistral for Llama, for DeepSeek, use it and see which model performs best,
switch off one model and replace it with another one” [DE2]. Data protection and security are far more pertinent factors in the choice between
OSAI and proprietary AI tools. This advantaged proprietary options in
some ways — “Microsoft already got all its contracting in place, did the
security review, certified it for protected B" [CA5] and “cyber security is an
issue we have to keep a close eye on for OSAI” [DE12] — and advantaged
OSAI on others — “so [if I was a security Agency], I would be getting my
open source models and I'd be stabilising them … I would want to be able to
air gap to make sure that whatever the large language model may have
gleaned or learned, that there's no global grounding in in what it's doing”
[AU7]. These considerations show the criticality of organisational factors – representing 57% of all code counts – and their interdependency
with technology choices. They also reflect how conceptions of security
when it comes to AI are still evolving, whereas OSS is seen as part of
traditional software implementation.
Digital sovereignty is adding further complication to the choice of AI.
Perhaps because an AI foundation model is not feasible to build in-house
— in comparison to a traditional software package — the dependence on
American providers is more strongly felt. DE6 stated that “sovereignty is
the number one decision factor, i.e. control over the AI system” while CA10
stated that their Agency had “interacted with Microsoft and Google but we
haven't take their AI because we want something Canadian”. The emergence
of DeepSeek during the interview period prompted many to comment
that lines in the sand were being drawn, for example: “DeepSeek might be
a stretch too far but we should at least consider running other Chinese [AI
models] on-prem” [DE5]. Even beyond sovereignty, some participants
called for AI models that reflected national conditions, e.g. “what does an
AI model for Australia built by Australia that has Australian values
embedded into the training of the model that represents Australia more
accurately look like?” [AU5]. That proprietary AI models couldn't be fully
interrogated was also an issue for security and privacy: “a lot of the
commercial models are very black box” [AU7]. However, AU5 pointed out
that the debates on which models were open-source weren't just semantic: “it's not really open-source unless you know what data it was trained
on. And we don't”.
4.2.4. Environmental dimension
External factors were seen to be less important in the choice of AI
than for traditional software, comprising just over a tenth of total code
counts. Open-source communities surrounding AI models were not seen
as developed and some had sprung out of less conventional places like
social media, e.g. “there's this Ollama community within Discord” [AU9].
AU5 expressed a fear that choosing an OSAI option would mean forgoing
the vendor support required to provide an “enterprise grade service to the
public”. Participants were either cautiously positive about contributing
back to an OSAI community or mildly negative: “you really need to keep
[it] tightly controlled” [AU3]. Like with communities around OSS, the
value was clear: “there's marvellous benefit to kind of having this ecosystem
of open standards and open code that would allow us to accelerate the kinds
of things we do” [CA8]. Internal consulting external to the Agency but
part of the wider government apparatus played a part in AU2 and AU9
implementing their AI solutions, while in Germany, the many government IT service providers play a strong and sometimes conflicting role.
Some Agencies lent on external resources when making decisions about
AI models — including Gartner, consultants and social media — for
example, AU4 explaining how a consultant might say, “we've used [an AI
solution] before 6 times. We know it's good”. In comparison, “[a suggestion
for an AI model is] potentially more likely to be open-source coming out of the
academic world because of the cost implications” [AU4]. The early stage of
specific guidance or regulation around AI choices meant these were not
influential, however, inter-Agency and even inter-state interaction
provided comparators to learn from. Each of the three countries had
communities of practice or cross-government working groups for AI
where insights could be shared, but German states were the most aware

of what each other were doing, with many pointing to Hamburg, Baden-
Württemburg and Schleswig-Holstein as distinct models of AI adoption
choices.
When asked to order their criteria for AI model choice, no uniform
ranking emerged. However, participants tended to focus on technical
considerations such as infrastructure and compatibility with the tech
stack, performance, control and quality, as well as security, sovereignty
and ethical factors.
5. Discussion
5.1. Contributions to research and theory
This study extends a line of scholarship on OSS adoption in the public
sector (e.g. Shaikh, 2016; Ven & Verelst, 2006), to compare and contrast
the contemporary stances on the choice to adopt OSS with that of OSAI.
There are differences in key decision-factors across all three TOE domains shown in Table 4:
This study provides several key contributions to the scholarship.
First, it is the only academic work identified to extend the extensive
literature on OSS take-up to OSAI adoption. It highlights that OSAI and
OSS have fundamentally different technical characteristics, meaning
assumptions made for OSS cannot be simply transposed onto OSAI.
Second, it leverages the insights of 31 senior decision-makers to build on
growing research on AI in the public sector by focusing specifically on
OSAI. Third, it contrasts AI adoption in three countries with distinct
technological adoption pathways. These underscore the impact of historical patterns of digitalisation, current perceptions of sovereignty, and
flow-on implications of AI choices for procurement, infrastructure
readiness and staff capability. It also has practical relevance for policymakers and public sector leaders, particularly those seeking to balance
between digital sovereignty and scaling of AI tools.
The differences in decision factors across domains and across jurisdictions shows the simple comparative power of TOE provide a framework to (attempt to) hold two dimensions constant while investigating
the third in-depth. More than three years into the current era of generative AI, Agencies are still adapting to an evolving technological landscape of AI model performance, costs and fit — echoing Shaikh's (2016)
focus on mutability of OSS — as well as organisational dynamics like the
attitudes of senior management and politicians. Even players within the
space are changing their strategies, for example, OpenAI has released
some of its models open-source (OpenAI, 2025). These dynamics support
the decision to ground this research in innovation diffusion and adoption. While OSAI was not seen as a clearly more innovative choice, it was
perceived as enabling more technological possibilities and optionality to
Agencies, in line with perceptions of OSS as innovative (Hauge et al.,
2010; Rossi et al., 2012). Furthermore, following on from findings that
Agencies deploying AI lack strong AI capabilities (Neumann et al., 2024;
Sienkiewicz-Małyjurek, 2023; Van Noordt & Tangi, 2023), the findings
show there is divergence between those with sufficient technical leadership and capability to open up a span of choices, which include opensource, and those that due to low internal capacity are only able to be
‘consumers’ of AI products, mainly proprietary ones.
Van Noordt and Tangi (2023) called for research on AI to be linked
with e-government scholarship. This contribution highlights how
themes prominent in e-government, including procurement capacity
and organisational culture, are now important influences in AI adoption
and choice between OSAI and proprietary alternatives. That organisational factors represented 57% of codes reflects previous findings from
Shaikh (2016), Freeman (2012), Zuliani and Succi (2004)and others on
the importance of organisational dynamics in technology choice. It is
ambiguous whether the evidence supports the strong role of individual
preferences and ideology in decision-making. On the one hand, decisionmakers supported the philosophy of open-source, however, in line with
the findings of Hauge et al. (2010), rational technical and economic
considerations were paramount in decision-makers' minds. In only a

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

very small number of cases did this extend to a cost-benefit analysis
common in asset ownership decisions, where investing in owning and
controlling an asset is highly determinant of later strategic decisions
(Baker & Hubbard, 2003). The homogeneity of OSAI models, frequent
release upgrade cycle and relative ease of switching makes loyalty towards one less strategically relevant and reduces incentives to invest in
it as an asset. Instead, Agencies' data infrastructure assets were a strong
determinant of whether local AI model deployment was feasible, with
those lacking on-premises assets reluctant to invest solely to adopt OSAI.
Nonetheless, the availability of OSAI models like Mistral and DeepSeek
on proprietary cloud platforms like Azure and AWS subverts the concept
of open-source adoption as in-sourcing: Agencies are not investing in
their own OSAI if they are merely connecting to an OSAI model's
endpoint in Azure or AWS in the same way as they would with a
ChatGPT endpoint. In the context of digital sovereignty, participants
recognised this dynamic, stating that AI decisions were not just about
the model used but also sovereign cloud infrastructure. Shaikh's (2016)
definition of open-source as the licence, community, code, coordinating
mechanisms and documentation seems foreign to how participants discussed OSAI. For example, licences were coded only 10 times (primarily
for German participants), the code is not as relevant for AI and community and coordinating mechanisms are still early in maturity. The
capabilities of Agencies' OSAI models are closely connected to the
original developer of the open-source foundation model (e.g. Mistral AI,
Meta and High Flyer). Agencies are reliant on these developers to release
updates and the high compute requirements to substantially re-train an
OSAI model mean that open-source communities play a lesser role than
in OSS adoption.
Which decision-makers make determine technology choices draws
on both innovation diffusion theory and institutional theory. Rogers
(2003) developed a typology of adopters, with most participants falling
into the innovator (at least in a public sector context) or early adopter
category by virtue of their role. The diversity of opinions, even within
the same country or government indicates that coercive isomorphism
(DiMaggio & Powell, 1983) is not yet present, potentially due to the lack
of published policies and guidance. Instead there was some evidence of
mimetic processes (ibid.), particularly in German and Canadian participants' close attention to developments in other Agencies, also reflecting
Rogers' (2003)communication channel dynamic. Further exploration of
how everyday exposure to AI (e.g. ChatGPT, Gemini) feeds into decision-

makers' perceptions was touched on by participants but would be
worthy of further study.
5.2. Limitations and gaps for future investigation
While this study presents the contemporary perspectives of a large
proportion of decision-makers on AI in three different country contexts,
it has some limitations. Firstly, it reflects self-reported perceptions and
stated preferences for certain attributes of OSAI and proprietary AI
rather than the revealed preferences in usage. Participants tended to
lean more optimistic regarding AI's potential, given the mandate of their
professional roles. Other staff in operational, risk or procurement roles
may have distinct views on OSAI adoption, affecting its potential takeup of the wider organisation. The semi-structured interview format
provided participants scope to talk to focus on topics they were most
interested in, providing an indication of the strength of certain factors
but inhibiting systematic comparison between cases. There may be selection bias from which decision-makers decided to participate, their
specific positions and responsibilities for adopting AI (e.g. delivery vs.
policy roles). Unfortunately, the scarcity of documentary evidence hindered further triangulation in the analysis. These limitations mean that
further research will be needed to confirm robustness and generalisability of the findings across countries, and whether the stated factors
are reflected in actual take-up. This includes temporal sensitivities, as
some participant responses may have been influenced by interview
timing, for example, in relation to DeepSeek's release and threats to
national sovereignty.
Agencies are also still evolving their strategies and approaches to AI
model choice, and data on which AI tools are deployed are sparse.
Systematically collected data on adoption patterns would complement
the study by comparing what is said with what actually occurs, with the
theme frequencies reflecting only coding densities within qualitative
transcripts. Furthermore, the study highlighted that there is a wide diversity of perspectives and experiences across a variety of Agencies.
Therefore, it is difficult to generalise and narrow down to a few key
factors – one reason why the TOE approach is suitable. De-identification
of participants also prevents deeper examination of Agency and individual contexts. As the study is the first to systematically look at OSAI in
the public sector context, it takes a broad lens to adoption. More detailed
examination of individual factors could provide researchers and policymakers with the drivers behind success or failure of different types of
AI adoption. Finally, the conceptualisation of ‘OSAI’ as simply capturing
open-source models is simplistic. This study used a pragmatic definition
of OSAI align with participants' perceptions and practical choices. It is
not clear the extent to which Agencies would be willing to trade-off key
attributes like performance to adopt maximally open-source models
such as EleutherAI's Pythia, opening a gap for further survey research. In
addition, there are many technical components surrounding an AI model
that enable it to function, which may or may not be open-source. Participants emphasised that there is no such thing as “an AI”, highlighting
the importance conceptualising an ecosystem of AI components that
enable steps like installation, fine-tuning and prompt engineering,
monitoring and assurance. As the field of research evolves, this should
be possible.
CRediT authorship contribution statement
Nicholas Robinson: Writing – review & editing, Writing – original
draft, Visualization, Validation, Supervision, Software, Resources,
Project administration, Methodology, Investigation, Formal analysis,
Data curation, Conceptualization.
Declaration of competing interest
The authors declare the following financial interests/personal relationships which may be considered as potential competing interests:

(1) The Australian Government’s Digital Transformation Agency is a
former employer of the author (2022-2024) with relevance to this
research. The author does not have any ongoing formal relationship
with this organization, and it has not had any influence over this study.
(2) The author divested from direct equity ownership in Microsoft
and Alphabet in July 2025 prior to any finalisation or publication of this
research and has no further material financial interest in these
Appendix A. Appendix 1
A.1. Key definitions of open-source
There is no binary definition separating open-source and proprietary
open-source and not, for example:
• Shaikh (2016): (1) licence, (2) community, (3) the code, (4) coordina
• S´anchez et al. (2020): A technical definitions based on Free / Libre /
• Schrepel and Pentland (2024) proposed an openness taxonomy to
competitive ecosystem
• Danish Board of Technology's 2004 definition of open standard (no lo

companies.
(3) The author has legally mandatory retirement (superannuation)
funds and Exchange Traded Fund holdings that may contain nonmaterial proportions of equities in related companies, including
Microsoft, Meta, Alphabet, etc.
(4) The author does not receive research funding outside of the salary
paid by the Hertie School as a Research Assistant.
odels. In an OSS context, scholars use various features to define what is
ng mechanisms, (5) documentation
pen-source Software (FLOSS)
ide policy recommendations that policymakers can use to maintain a
ger available but displayed in Rossi et al. (2012)): Ongoing access free of

• Danish Board of Technology's 2004 definition of open standard (no longer available but displayed in Rossi et al. (2012)): Ongoing access free of
charge with no discrimination between users nor option to limit access later, with full documentation of all aspects.
A taxonomy spectrum is one way to tackle the differences (The Economist, 2024), and can be defined by identifying the key differences that make a
model more open or closed, primarily relating to access to technical components such as model weights, commercial restrictions like licences and how
the product itself can be used. These differences are shown in Table 5:

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

2025) Databricks's Dolly model models
Based on Azoulay et al. (2024), The Economist (2024), Borg et al. (2019), Shaikh (2016), Schrepel and Pentland (2024), Lin (2024), Yan (2025), Liesenfeld and
Dingemanse (2024), Open Source Initiative, 2026. Note that none of the prominent OSAI models, even those categorised here as ‘unrestricted open-source' disclose
their training data and therefore may not be seen as ‘maximally open-source'.
From the perspective of public administrations, certain AI model types on the openness spectrum may be better considered as a highly configurable
off-the-shelf tool, given that many of these organisations will access open-source models through a third-party cloud platform such as Microsoft Azure
or AWS. This is backed up by literature on OSS, e.g. from Ajila and Wu (2007) and Li et al. (2006).
A.2. Differences between OSAI and OSS
OSAI has notably distinct attributes from OSS, both in technical and adoption terms. Table 6 summarises key differences (which, due to the diversity of traditional software and AI models are in some cases generalisations) at different stages of development and use:

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

Based on Bateman et al. (2024), Azoulay et al. (2024), Borg et al. (2019), Sa´nchez et al. (2020), Shaikh (2016), Schrepel and Pentland (2024), Yan (2025), as well as
observations from interview participants.
While the distinctions between OSAI and OSS are evolving (Bateman et al., 2024), they also reflect fundamental differences between AI and
traditional software. Further research on the technical and adoption differences between the two categories will help scholars and practitioners
understand how conceptions of open-source are changing.
A.3. Current state of prominent OSAI models
Meta's Llama models are primarily used when embedded in their products such as Instagram, Messenger and WhatsApp. Meta made Llama 4
available for download, although there are still some restrictions on use over and above a typical open-source licence (e.g. Apache 2.0, MIT). Mistral AI
has partnered with Microsoft and now charges for some of its models (Lex, 2024). Chinese firm DeepSeek emerged with its R1 and V3 models claimed
to be trained using a relatively small amount of computing power, which they have continued to open-source and allow others such as Tencent to
create APIs for (Gibney, 2025; Roose, 2025; Wu, 2025). Alphabet released lower-capability Gemini models as open-source while OpenAI released a
suite of lower-powered open-source models in mid-2025 (OpenAI, 2025; Seetharaman, 2025).
Appendix B. Appendix 2
B.1. Interview guide
The interview guide was developed using two main sources:
• Research themes, findings and interview guides from research on OSS adoption (e.g. Shaikh (2016), Ven and Verelst (2006), Freeman (2012),
S´anchez et al. (2020)) formed the basis for the guide structure, influencing key themes and the flow of questions.
• Research on AI adoption (e.g. Madan and Ashok (2023), Mergel et al. (2023), Hickok (2024), Van Noordt and Tangi (2023)) was used to inform
contextual questions about AI adoption.
As the Research Questions were framed to compare OSS and OSAI adoption, it was important to ensure that the interview guide covered the key
themes identified in OSS adoption literature, as well as covering all three elements of the TOE framework. Questions were structured into five sections:
Context, AI initiation and implementation, open-source, decision-making, enablers and flow-on effects. The discussion of open-source was deliberately
placed after understanding the AI projects, in order not to bias the discussion towards the open-source vs. proprietary choice. The German interview
guide was substantively identical.
1. What is the organisation you work in? What is your role?
2. How does your organisation currently use AI?
3. How would you describe the current capability and maturity regarding AI adoption in the organisation?
4. How familiar are you with different of AI models? Where do you find out about these models?
5. What are the key use cases that you see AI being used in your organisation?
6. How is AI adoption situated in the organisation? Is it confined to the function responsible for AI or connected throughout the organisation?
7. Has AI adoption affected how the organisation works?
8. What were the reasons why the organisation went with its current AI model choices?
9. What factors would make adoption of open-source or proprietary AI more or less prevalent? In which contexts are each more appropriate? What
are the decision factors that were most influential?
10. How would you describe the broad attitude towards open-source software in the organisation? What factors drive this attitude? How would you
describe the evolution of OSS in the organisation? What was this informed by?
11. How do you see open-source AI being different from open-source software?
12. Who makes decisions about what major technologies to use? Is this the same as for AI models?
13. How are these decisions justified and realised in the organisation? What is required? Who is involved? Are actors outside the Agency involved?
14. Do you rely on any specific internal or external expertise or information to inform AI or broader technology adoption?
15. What are the internal and external enablers for AI implementation?
16. Are there any further considerations you would like to mention?

Appendix C. Appendix 3
C.1. Summary of thematic code definitions (by TOE dimension, then in order of frequency)
Factors Summary of definitions, exclusions and clarifications
Technology
Ongoing cost Reflects ongoing or operational economic investments to continue using the tool, including maintenance costs and effort, further investment
requirements for upgrades, as well as avoided cost from not needing to build again.
Performance Reflects the perceived performance of the tool procured or taken, involving aspects such as accuracy, speed, reduced error rate, retrieving or
augmenting with additional information. Exclusion: Does not include material refinements made by the Agency itself to the tool.
Cost upfront Reflects the one-off economic investments needed to adopt the tool, including purchase prices, buying new hardware or licences, investing in
upgrades.
Ease of implementation Reflects perceived ease of installing integrating the tool into the Agency's environment as well as the ability for workers to adapt to the new way of
working.
Physical infrastructure Reflects the technology hardware capacity of the Agency and its ‘on-premises’ readiness to adopt the new tool, including servers, GPUs,
processing units and other aspects of data centre establishment such as cooling.
Product fit Reflects whether tool can achieve what the intended purpose requires and has the desired attributes, which may be signalled by users being eager
to use it and recommending it to others. Exclusions: Does not relate to how the tool's capabilities or usefulness are perceived in the market.
Tuning Reflects a deeper level of customisation of the tool, including fine-tuning, post-training and prompt engineering, both of internal-developed and
externally-procured tools.
Fit with existing tech-stack Reflects the alignment of the tool's technical specifications with the Agency's existing technology stack, including its existing software and
architectural standards.
Data maturity Reflects the preparedness of data management, structures, architectures, as well as the overall quality of data in the Agency.
Innovation Reflects the Agency adopting innovative practices or experimenting with new approaches to AI or traditional software adoption. Exclusions: Does
not relate to ‘everyday’ adoption of new technologies.
Cloud Reflects the capacity of the Agency to utilise or deploy cloud data storage and processing infrastructure (as distinct from ‘on-premises’) and the
interest in doing so, including from non-sovereign and commercial providers but also internally managed cloud deployments.
Debugging and useability Reflects adjustment of the tool to address usability or reliability challenges or errors. Exclusions: Does not include improvements made by the
Agency to the tool to improve its performance or fit.
Linked data Reflects whether data are sufficiently linked across the Agency such that the tool can be effectively adopted, including siloed data holdings,
accessibility of data and awareness of the issue. Exclusion: Does not relate to the quality and maturity of data structures, only whether data can be
readily linked.
Licensing Reflects the extent to which licensing of the tool (e.g. MIT, Apache, etc.) is a consideration in decision-making and its adoption, as well as
Agencies licensing internally-developed tools for external use.
Flexibility Reflects the ability of the Agency to adapt the tool to its uses. Exclusion: Does not relate to technical tuning of a tool (covered in ‘Tuning’) nor
fixing of operational issues (covered in ‘Debugging’)
Organisation
Decision-maker support Reflects instances of a decision-maker influencing the decision to adopt the technology, including the participant themselves if they are a
decision-maker.
Security Reflects how adoption of a tool may impact the Agency and government's security (not just IT security) from adoption of the tool, including
hacking, data or system breaches, as well as any defensive attributes or mitigations that have been put in places and organisational sensitivities
around this issue.
Staff capability Reflects the capabilities, specified skills and capacities of Agency employees and its ability to attract the right talent for the tasks required of it.
Exclusions: Does not relate to technological readiness for changes in technology, nor a less specific form of technical sophistication than skills or
capabilities.
Policies Reflects the existence and influence of government policies and strategies on the decision and approach to decision-making around the tool and its
adoption, including related instruments such as standards, designs, mandatory guidance.
Lock-in Reflects dependencies on vendors, how they come about, when they are exacerbated, including aspects such as contracting, legal, technical
inertia, the impact of brand and reputation on willingness to change. Exclusion: Does not relate to the power of brand or reputation itself, only
when that becomes a key driver for maintaining a status quo.
Organisational technical Reflects the technical sophistication of the whole Agency, specifically its readiness to adopt a new tool, including awareness of key concepts,
sophistication readiness to adopt new tools and attitude towards new technologies.
Procurement Reflects the processes and structures for procuring technologies, the team responsible for this and influence over decision-making and adoption of
the tool.
Digital sovereignty Reflects how adoption of a tool may impact the sovereignty of a country, government or Agency, including its ability to make sovereign decisions.
Inter-Agency collaboration Reflects Agencies and governments working together (intra-government, intra-country and internationally), including through marketplace
mechanisms and facilitating reuse of the tool by others for common benefit. Exclusion: Does not relate to open-source communities or
collaborative arrangements.
Organisational attitude towards Reflects the attitude or stance of the broader Agency towards open-source technologies in comparison to proprietary or commercial technologies.
OSS Clarification: This relates more to general attitudes than critique or praise of specific attributes of open-source or proprietary technologies.
Culture Reflects the attitude of the Agency towards change, risk, technological improvement, and the trust in the technical team (in this context) to
design, develop and manage adoption of new technological tools. Exclusion: Does not include experience or capabilities.
Team attitude towards OSS Reflects the attitude or stance of the immediate team around the participant (and the participant themselves) towards open-source technologies in
comparison to proprietary or commercial technologies. Clarification: This relates more to general attitudes than critique or praise of specific
attributes of open-source or proprietary technologies.
Resources and guidance Reflects the existence and influence of non-mandatory guidance material or external resources utilised by decision-makers and their teams to
shape decision-making and adoption of the tool, including reports mentioned as useful.
Role of the central government Reflects the role and influence of the central (federal) government in enabling adoption of desired tools, such as building shareable infrastructure,
coordinating policies and providing funding.
Privacy and IP protection Reflects how a tool may impact sensitive data held about citizens, government employees and businesses (including commercial data) and
organisational sensitivities around this issue, including protection of data rights and IP.
Regulation Reflects how regulations, legislation (including proposed legislation) may influence adoption of the tool, as well as government legal litigation
based on regulation.
Administrative Reflects the administrative or bureaucratic impacts of the adoption of the tool on the Agency, including how administrative work changes.
Transparency Reflects the extent to which the Agency can interrogate the process, mechanics and data used to generate a decision using a tool.
(continued on next page)

(continued)
Factors Summary of definitions, exclusions and clarifications
In-the-loop Reflects to whether responsible humans can or need to oversee and guardrails put in place to ensure humans stay in control.
Fairness Reflects whether the tool is or would be perceived as behaving fairly when deployed, including the impact of in-built biases, and the ability to
mitigate these issues.
Team technical sophistication Reflects the technical sophistication of immediate team around the participant (generally a technical team) that is at the frontline of adopting the
tool, including knowledge of key concepts, readiness to deploy the tool and attitude towards cutting-edge technologies. Exclusion: Does not relate
to skill and staff capacity aspects of the Agency's broader staff capability (although there is likely substantial correlation with Staff Capability), nor
the organisational attitudes to risk and change covered in Culture.
IT team Reflects the influence, behaviours and attitudes of the internal IT team responsible for managing adoption of new tools and technologies.
Exclusion: Does not relate to an internal consulting arrangement from a team that does on-demand tasks and may be subject to an internal funding
arrangement.
Accountability Reflects who would be held responsible for adoption of the tool and its impacts, which may be an external vendor or an internal actor or team.
Environment
Community Reflects the establishment, role, value of an open-source or collaborative community related to a tool, what incentives or structures need to be put
in place to maintain the community.
Competition Reflects to the market dynamics, competition between vendors and developers, ways in which competition is influenced such as lobbying.
Exclusion: Does not relate to the technical attributes of the tool or its brand or reputation except if they explicitly become a competitive dynamic.
Internal support Reflects the support, advice and assistance for adoption of the tool from internal consulting teams and shared services functions. Exclusion: Does
not relate to support from internal teams that have a purely technical support function, which are captured under IT teams.
Vendor and tech support Reflects the support, advice and assistance for adoption of the tool from technology firms, primarily the developer of the tool but also other
relevant firms providing technical components.
Consulting support Reflects the support, advice and assistance for adoption of the tool from commercial consulting firms.
Academic support Reflects the support, advice and assistance for adoption of the tool from academic partners, including collaborations with universities and
institutes to develop or improve the tool.
Reputation and brand Reflects the role of the tool's brand power and reputation in the perceptions and decision-making related to the tool, including awareness of the
brand, its heritage, how it is discussed, its country of origin. Exclusion: Does not relate to concerns about the tool's technical attributes (e.g.
security, privacy, fairness) nor sovereignty.
References Chen, T., Gasco´-Hernandez, M., & Esteve, M. (2024). The adoption and implementation
of artificial intelligence chatbots in public organizations: Evidence from US state
governments. The American Review of Public Administration, 54(3), 255–270.
Ajila, S. A., & Wu, D. (2007). Empirical study of the effects of open source adoption on
Davis, F. D. (1989). Technology acceptance model: TAM. In MN Al-Suqri, & AS Al-Aufi
software development economics. Journal of Systems and Software, 80(9),
(Eds.), 205. Information Seeking Behavior and Technology Adoption (p. 5) (219).
1517–1529.
Dedrick, J., & West, J. (2004). An exploratory study into open source platform adoption.
Azoulay, P., Krieger, J. L., & Nagaraj, A. (2024). Old moats for new models: Openness,
Systems sciences. In Proceedings of the 37th Annual Hawaii International Conference.

Azoucloanyt,r oPl.,, aKnrdi ecgoemr,p Jet.i tLio.,n & in N gaegnaerraajt,i vAe . A(I2 0(V24ol).. NOold. wm3o2a4ts7 4fo)r. nNeawti omnoadl eBlsu: rOeapeun onfe ss,
Economic Research. https://www.nber.org/papers/w32474.
Badampudi, D., Wohlin, C., & Petersen, K. (2018). Software component decision-making:
In-house, OSS, COTS or outsourcing — A systematic literature review. Journal of
Systems and Software, 121, 105–124.
Baker, G. P., & Hubbard, T. N. (2003). Make verses buy in trucking: Asset ownership, job
design and information (NBER working paper Vol. No. 8727). National Bureau of
Economic Research. http://www.nber.org/papers/w8727.
Baregheh, A., Rowley, J., & Sambrook, S. (2009). Towards a multidisciplinary definition
of innovation. Management Decision, 47(8), 1323–1339.
Bateman, J., Baer, D., Bell, S. A., Brown, G. O., Cu´ellar, M., Ganguli, D., Henderson, P.,
Kotila, B., Lessig, L., Berild Lundblad, N., Napolitano, J., Raji, D., Seger, E.,
Sheehan, M., Skowron, A., Solaiman, I., Toner, H., & Zvyagina, P. (2024). Beyond
Open vs. Closed: Emerging Consensus and Key Questions for Foundation AI Model
Governance. Carnegie Endowment for International Peace. Retrieved from https:
//carnegieendowment.org/research/2024/07/beyond-open-vs-closed-emergingconsensus-and-key-questions-for-foundation-ai-model-governance?lang=en.
(Accessed 15 January 2026).
Bommasani, R., Hudson, D. A., Adeli, E., Altman, R., Arora, S., von Arx, S., …
Brunskill, E. (2021). On the opportunities and risks of foundation models. Stanford
University Centre for Research on Foundation Models. Retrieved from: https://crfm.
stanford.edu/report.html Accessed 15 March 2026.
Borg, M., Chatzipetrou, P., Wnuk, K., Al´egroth, E., Gorschek, T., Papatheocharous, E., …
Axelsson, J. (2019). Selecting component sourcing options: A survey of software
engineering’s broader make-or-buy decisions. Information and Software Technology,
112, 18–34.
Bouras, C., Filopoulos, A., Kokkinos, V., Michalopoulos, S., Papadopoulos, D., &
Tseliou, G. (2014). Policy recommendations for public administrators on free and
open source software usage. Telematics and Informatics, 31(2), 237–252.
Bright, J., Enock, F., Esnaashari, S., Francis, J., Hashem, Y., & Morgan, D. (2025).
Generative AI is already widespread in the public sector: Evidence from a survey of
UK public sector professionals. Digital Government: Research and Practice, 6(1), 1–13.
Brynjolfsson, E., Li, D., & Raymond, L. (2023). The impact of generative AI on customer
support agent productivity (Vol. No. w31161). National Bureau of Economic Research.
https://www.nber.org/papers/w31161.
Burkhardt, S., & Rieder, B. (2024). Foundation models are platform models: Prompting
and the political economy of AI. Big Data & Society, 11(2). https://doi.org/10.1177/
20539517241247839
Chang, A. (2024). Risk aversion and public sector employment. Public Administration
Review, 84(5), 833–847.

Systems sciences. In Proceedings of the 37th Annual Hawaii International Conference.
https://doi.org/10.1109/HICSS.2004.1265633
DiMaggio, P. J., & Powell, W. W. (1983). The iron cage revisited: Institutional
isomorphism and collective rationality in organizational fields. American Sociological
Review, 48(2), 147–160.
Edquist, C., & Hommen, L. (2000). Public technology procurement and innovation
theory. In C. Edquist, L. Hommen, & L. Tsipouri (Eds.), Public technology procurement
and innovation (pp. 5–70). Boston, MA: Springer US.
Eisenhardt, K. M. (1989). Building theories from case study research. Academy of
Management Review, 14(4), 532–550.
Fitzgerald, B. (2009). Open-source software adoption: Anatomy of success and failure.
International Journal of Open-source Software and Processes, 1(1), 1–23.
Floridi, L., Buttaboni, C., Hine, E., Novelli, C., Schroder, T., & Shanklin, G. (2025). Opensource AI made in the EU: Why it is a good idea. Minds and Machines, 35(2), 23.
https://doi.org/10.1007/s11023-025-09728-x
Freeman, S. (2012). User freedom or user control?: The discursive struggle in choosing
among free/libre open source tools in the Finnish public sector. Information
Technology & People, 25(1), 103–128.
Fusch, P. I., & Ness, L. R. (2015). Are we there yet? Data saturation in qualitative
research. The Qualitative Report, 20(9), 1408–1416.
Gibney, E. (2025). China’s cheap, open AI model DeepSeek thrills scientists. Nature, 638,
13–14. https://doi.org/10.1038/d41586-025-00229-6
Gurusamy, K., & Campbell, J. (2012). Enablers of open source software adoption: A case
study of APS organizations. Australasian Journal of Information Systems, 17(2), 3–5.
https://doi.org/10.3127/ajis.v17i2.731
Haug, N., Dan, S., & Mergel, I. (2024). Digitally-induced change in the public sector: A
systematic review and research agenda. Public Management Review, 26(7),
1963–1987. https://doi.org/10.1080/14719037.2023.2234917
Hauge, Ø., Ayala, C., & Conradi, R. (2010). Adoption of open source software in
software-intensive organizations – A systematic literature review. Information and
Software Technology, 52(11), 1133–1154. https://doi.org/10.1016/j.
infsof.2010.05.008
Hickok, M. (2024). Public procurement of artificial intelligence systems: New risks and
future proofing. AI & Society, 39, 1213–1227. https://doi.org/10.1007/s00146-022-
01572-2
Hjaltalin, I. T., & Sigurdarson, H. T. (2024). The strategic use of AI in the public sector: A
public values analysis of national AI strategies. Government Information Quarterly, 41
(1), Article 101914. https://doi.org/10.1016/j.giq.2024.101914
Holck, J., Larsen, M. H., & Pedersen, M. K. (2005). Managerial and technical barriers to
the adoption of open source software. In International Conference on COTS-Based
Software Systems, Berlin.

Hsieh, H. F., & Shannon, S. E. (2005). Three approaches to qualitative content analysis.
Qualitative Health Research, 15(9), 1277–1288. https://doi.org/10.1177/
1049732305276687
Landesportal Schleswig-Holstein. (2025). Open-source-strategie Schleswig-Holstein.
Retrieved from https://www.schleswig-holstein.de/DE/landesregierung/themen/di
gitalisierung/linux-plus1 Accessed 17 July 2025.
Lex. (2024). How ‘open’ is generative AI really? Not very. Financial Times. Retrieved from
https://www.ft.com/content/a09e4aaf-be52-4a45-86a7-c6d1636526bcAccessed 17
July 2025.
Li, J., Conradi, R., Slyngstad, O. P. N., Bunse, C., Torchiano, M., & Morisio, M. (2006). An
empirical study on decision making in off-the-shelf component-based development.
In Proceedings of the 28th International Conference on Software Engineering (pp.
897–900). New York, NY.
Liesenfeld, A., & Dingemanse, M. (2024). Rethinking open-source generative AI: openwashing and the EU AI Act. In Proceedings of the 2024 ACM Conference on Fairness,
Accountability, and Transparency (pp. 1774–1787).
Lin, B. (2024). Open-source companies are sharing their AI free. In Can they crack
OpenAI’s dominance?. Wall Street Journal. Retrieved from https://www.wsj.com/ar
ticles/open-source-companies-are-sharing-their-ai-free-can-they-crack-openais-dom
inance-26149e9c Accessed 10 July 2025.
Madan, R., & Ashok, M. (2023). AI adoption and diffusion in public administration: A
systematic literature review and future research agenda. Government Information
Quarterly, 40(1), Article 101774.
Medappa, P. K., & Srivastava, S. C. (2020). Ideological shifts in open source
orchestration: Examining the influence of license choice and organizational
participation on open source project outcomes. European Journal of Information
Systems, 29(5), 500–520.
Mergel, I., Dickinson, H., Stenvall, J., & Gasco, M. (2023). Implementing AI in the public
sector. Public Management Review, 1–14. https://doi.org/10.1080/
14719037.2023.2231950
Mikalef, P., Lemmer, K., Schaefer, C., Ylinen, M., Fjørtoft, S. O., Torvatn, H. Y., …
Niehaves, B. (2022). Enabling AI capabilities in government agencies: A study of
determinants for European municipalities. Government Information Quarterly, 39(4),
Article 101596. https://doi.org/10.1016/j.giq.2021.101596
Munoz-Cornejo, G., Seaman, C. B., & Koru, A. G. (2008). An empirical investigation into
the adoption of open source software in hospitals. International Journal of Healthcare
Information Systems and Informatics (IJHISI), 3(3), 16–37.
Neumann, O., Guirguis, K., & Steiner, R. (2024). Exploring artificial intelligence adoption
in public organizations: A comparative case study. Public Management Review, 26(1),
114–141.
Noronha, F. (2002). Europe Takes a Deeper Look at Free/Libre and Open-Source
Software, Linux Journal. Retrieved from https://www.linuxjournal.com/art
icle/6354 Accessed 17 August 2025.
Open Source Initiative. (2026). The open source AI definition – 1.0. Open-source-aidefinition. Retrieved from https://opensource.org/ai/open-source-ai-definition
Accessed 13 January 2026.
OpenAI. (2025). Open models by OpenAI. Retrieved from https://openai.com/open-mode
ls/. Accessed 10 September 2025.
Osborne, C., Ding, J., & Kirk, H. R. (2024). The AI community building the future? A
quantitative analysis of development activity on hugging face hub. Journal of
Computational Social Science, 7(2), 2067–2105.
Pumplun, L., Tauchert, C., & Heidt, M. (2019). A new organizational chassis for artificial
intelligence-exploring organizational readiness factors. In Proceedings of the 27th
European Conference on Information Systems (ECIS), Stockholm & Uppsala, Sweden,
June 8–14, 2019. ISBN 978–1–7336325-0-8 Research Papers https://aisel.aisnet.
org/ecis2019_rp/106.
Raymond, E. S. (2000). The cathedral and the bazaar. Retrieved from https://creatingac
tion.stanford.edu/pdf/cathedral-bazaar.pdf Accessed 13 March 2025.
Rogers, E. M. (2003). Diffusion of innovations (5th ed.). New York, NY: Free Press.
Roose, K. (2025). Why DeepSeek could change what Silicon Valley believes about AI. New
York Times. Retrieved from https://www.nytimes.com/2025/01/28/technology/ch
ina-deepseek-ai-silicon-valley.html Accessed 17 August.
Rossi, B., Russo, B., & Succi, G. (2012). Adoption of free/libre open source software in
public organizations: Factors of impact. Information Technology and People, 25(2),
156–187.
Ryan, B., & Gross, N. C. (1943). The diffusion of hybrid seed corn in two Iowa
communities. Rural Sociology, 8(1), 15.
Sa´nchez, V. R., Ayuso, P. N., Galindo, J. A., & Benavides, D. (2020). Open source
adoption factors — A systematic literature review. IEEE Access, 8, 94594–94609.
https://doi.org/10.1109/ACCESS.2020.2993248

Schofield, J. (2001). The old ways are the best? The durability and usefulness of
bureaucracy in public management. Organization, 8(1), 77–96.
Schrepel, T., & Pentland, A. S. (2024). Competition between AI foundation models:
Dynamics and policy recommendations. Industrial and Corporate Change. , Article
dtae042. https://doi.org/10.1093/icc/dtae042
Seetharaman, D. (2025). Sam Altman’s answer to DeepSeek is giving away OpenAI’s tech.
Wall Street Journal. Retrieved from https://www.wsj.com/tech/ai/sam-altmans-a
nswer-to-deepseek-is-giving-away-openais-tech-d1a5a9ec Accessed 17 July 2025.
Shaikh, M. (2016). Negotiating open source software adoption in the UK public sector.
Government Information Quarterly, 33(1), 115–132. https://doi.org/10.1016/j.
giq.2015.11.001
Shaw, A. (2011). Insurgent expertise: The politics of free/livre and open source software
in Brazil. Journal of Information Technology & Politics, 8(3), 253–272.
Sienkiewicz-Małyjurek, K. (2023). Whether AI adoption challenges matter for public
managers? The case of Polish cities. Government Information Quarterly, 40(3), Article
101828. https://doi.org/10.1016/j.giq.2023.101828
Stewart, K. J., & Gosain, S. (2006). The impact of ideology on effectiveness in open
source software development teams. MIS Quarterly, 30(2), 291–314. https://doi.org/
10.2307/25148732
Straub, V. J., Morgan, D., Bright, J., & Margetts, H. (2023). Artificial intelligence in
government: Concepts, standards, and a unified framework. Government Information
Quarterly, 40(4), Article 101881. https://doi.org/10.1016/j.giq.2023.101881
Tarkowski, A., & Open Futures. (2025). Data governance in open source AI: Enabling
responsible and systemic access. Retrieved from https://opensource.org/data-govern
ance-open-source-ai Accessed 13 January 2026.
The Economist. (2024). Meta is accused of “bullying” the open-source community.
Retrieved from https://www.economist.com/business/2024/08/28/meta-is-accuse
d-of-bullying-the-open-source-community Accessed 20 July 2025.
Timmermans, S., & Tavory, I. (2012). Theory construction in qualitative research: From
grounded theory to abductive analysis. Sociological Theory, 30(3), 167–186.
Tornatzky, L. G., & Fleischer, M. (1990). The processes of technological innovation.
Lexington Books.
Van Loon, A., & Toshkov, D. (2015). Adopting open source software in public
administration: The importance of boundary spanners and political commitment.
Government Information Quarterly, 32(2), 207–215. https://doi.org/10.1016/j.
giq.2015.01.004
Van Noordt, C., & Tangi, L. (2023). The dynamics of AI capability and its influence on
public value creation of AI within public administration. Government Information
Quarterly, 40(4), Article 101860. https://doi.org/10.1016/j.giq.2023.101860
Ven, K., & Verelst, J. (2006). The organizational adoption of open source server software
by Belgian organizations. In IFIP International Conference on Open Source Systems (pp.
111–122). Boston, MA: Springer US.
Venkatesh, V., Morris, M. G., Davis, G. B., & Davis, F. D. (2003). User acceptance of
information technology: Toward a unified view. MIS Quarterly, 27(3), 425–478.
https://doi.org/10.2307/30036540
Widder, D. G., Whittaker, M., & West, S. M. (2024). Why ‘OPEN’AI systems are actually
closed, and why this matters. Nature, 635(8040), 827–833.
Wirtz, B. W., Weyerer, J. C., & Geyer, C. (2019). Artificial intelligence and the public
sector—Applications and challenges. International Journal of Public Administration, 42
(7), 596–615. https://doi.org/10.1080/01900692.2018.1498103
Wu, Z. (2025). DeepSeek focuses on research over revenue in contrast to Silicon Valley.
Financial Times. Retrieved from https://www.ft.com/content/fb5c11bb-1d4b-465
f-8283-451a19a3d425 Accessed 17 August 2025.
Yan, E. (2025). open-llms. GitHub. Retrieved from https://github.com/eugeneyan/
open-llms/blob/main/README.md Accessed 17 August 2025.
Zuliani, P., & Succi, G. (2004). Migrating public administrations to open source software.
In E-society IADIS International Conference (pp. 829–832). Avila, Spain.
Nicholas Robinson (Nick) is part of the Hertie School's Centre for Digital Governance in
Berlin, working as Research Associate and PhD researcher. He was previously an Assistant
Director at the Australian Government's Digital Transformation Agency, where he led the
establishment of the Government's AI Taskforce in 2023. Prior to this, he undertook a data
science Masters at ESCP in Paris and Berlin and was a public policy economist at PwC
Strategy& for six years. Nick's interests lie in understanding how the paradigms, capabilities and processes that underpin public sector digitalization and digital transformation
should to be adapted for successful governance and adoption of AI.
