"""Compile the source-backed navigation catalog. No network or credentials required."""
import json,re,sys
from pathlib import Path
from urllib.parse import urlsplit
from pypdf import PdfReader
sys.stdout.reconfigure(encoding='utf-8')
PROJECT=Path(__file__).resolve().parents[1]
WORKSPACE=PROJECT.parent
pdf=PdfReader(r'D:/QQ/2026年福建省大学生信息素养大赛客观题命题范围及备赛建议.pdf')
categories=[
 ('ai','AI 素养','AI工具'),('government','政府开放信息','政府信息'),('learning','实用学习资源','学习资源'),('academic','学术信息资源','学术资源'),('systems','信息检索系统','检索系统'),('retrieval','检索理论与技术','检索技术'),('knowledge','知识管理工具','知识管理'),('writing','学术写作','学术写作'),('research','科研工具','科研工具'),('campus','校内与赛事','校内赛事')]
ranges=[(1,7,'ai'),(8,16,'government'),(17,20,'learning'),(21,25,'academic'),(26,30,'systems'),(31,37,'retrieval'),(38,41,'knowledge'),(42,45,'writing'),(46,50,'research')]
moduleCategory={n:c for low,high,c in ranges for n in range(low,high+1)}
scope=(WORKSPACE/'skills/fj-information-literacy/references/scope.md').read_text(encoding='utf-8')
modules={};pageToModule={}
for n,title,start,end in re.findall(r'\|(\d{2})\|([^|]+)\|(\d+)—(\d+)\|',scope):
 modules[int(n)]=re.split(r'[－-]',title,maxsplit=1)[-1].strip()
 for p in range(int(start),int(end)+1):pageToModule[p]=int(n)
# name | url | primary category | modules | purpose | short mark
seed='''
中国知网|https://www.cnki.net/|academic|11,12,21,22,23,31,32,34,35,36,42,44,47,50|中文论文、学位论文、会议文献、专利与标准检索|CN
万方数据|https://www.wanfangdata.com.cn/|academic|11,12,21,22,23,31,32,34,35,36,42,44,47,50|学术文献检索、结果筛选与参考文献导出|万方
维普|https://www.cqvip.com/|academic|11,12,21,22,23,31,32,34,35,36,42,44,50|中文期刊、学位论文及其他文献资源检索|维普
DeepSeek|https://chat.deepseek.com/|ai|3,48|通用 AI 对话、问题分析与数据处理辅助|DS
豆包|https://www.doubao.com/|ai|3,4,5,6,38,49|AI 问答、办公创作、多模态生成与数据分析|豆
腾讯元宝|https://yuanbao.tencent.com/|ai|3|腾讯 AI 助手，进入原平台选择模型和功能|元
Kimi|https://www.kimi.com/|ai|3,4|长文阅读、资料整理与 PPT 辅助创作|K
智谱清言|https://chatglm.cn/|ai|3,4,6,39|AI 阅读、PPT 创作、图像与视频相关工具|GLM
千问（通义）|https://www.qianwen.com/|ai|3,4,38|通用 AI、办公创作与记录整理|Q
讯飞星火|https://xinghuo.xfyun.cn/|ai|3,4,6|AI 对话、写作与图像创作辅助|星火
文心助手|https://wenxin.baidu.com/|ai|3,4,6|百度 AI 助手，办公、学习与内容创作|文心
纳米 AI|https://www.n.cn/|ai|3|AI 搜索与通用智能工具入口|纳米
CNKI AI|https://ai.cnki.net/chat/home|ai|5,50|知识问答、智能研读与学术趋势分析|AI
LeapSpace|https://www.sciencedirect.com/leapspace|ai|5,21,24,42|科研 AI 平台、文献探索与投稿辅助|LS
星火科研助手|https://paper.iflytek.com/|ai|5|文献阅读、学术翻译和写作辅助|研
秘塔 AI 搜索|https://metaso.cn/|ai|5|带来源的 AI 搜索与资料研究|秘塔
AMiner|https://www.aminer.cn/|ai|5,26|学术搜索、科研人物与科技情报|AM
万相|https://tongyi.aliyun.com/wan/|ai|6|AI 图像与视频生成平台|万相
可灵 AI|https://klingai.com/cn/|ai|6|图像和视频生成工具入口|可灵
闪剪|https://shanjian.tv/|ai|6|数字人与视频制作工具|闪剪
蝉镜|https://www.chanjing.cc/|ai|6|AI 数字人及内容创作工具|蝉镜
GitHub|https://github.com/|ai|7|查开源代码、README、许可证与发布版本|GH
魔搭 ModelScope|https://modelscope.cn/|ai|7|模型、数据集与应用体验资源|MS
百度 AI Studio|https://aistudio.baidu.com/|ai|7,18,48|人工智能课程、项目案例与开放数据集|AI
和鲸社区|https://www.heywhale.com/|ai|7,18|数据科学学习项目、训练营与数据集|鲸
阿里云天池|https://tianchi.aliyun.com/|ai|7,18,48|数据竞赛、课程与数据集|天池
DataFountain|https://www.datafountain.cn/|ai|7,18|数据竞赛、赛题说明与数据资源|DF
OpenDataLab|https://opendatalab.com/|ai|7,48|开放数据集、文件格式与资源下载|OD
OpenML|https://www.openml.org/search?type=data|ai|7,48|机器学习数据集与任务资源|ML
UCI 数据集库|https://archive.ics.uci.edu/|ai|7,48|机器学习数据集、字段与样本说明|UCI
UCI Beta 数据集库|https://archive-beta.ics.uci.edu/|ai|7|材料列出的新版数据集库入口|UCI
阿里云 AI 学习路线|https://developer.aliyun.com/learning/roadmap/ai|ai|2|人工智能学习路线与开发者课程|阿里
AI 大学堂|https://www.aidaxue.com/|ai|2|科大讯飞 AI 学习资源|AI
华为昇腾 AI 学堂|https://ascend.developer.huaweicloud.com/home|ai|2|昇腾 AI 专区与学习资源|昇腾
动手学深度学习|https://zh.d2l.ai/|ai|2|开源深度学习教材与代码实践|D2L
Elements of AI|https://www.elementsofai.com/|ai|2|人工智能基础学习课程|AI
深大图书馆 AI 专题|https://www.lib.szu.edu.cn/learning/ai|ai|2|生成式 AI 简介、政策与工具导航|深大
习近平重要讲话数据库|http://jhsjk.people.cn/|government|8|按标题、全文和时间检索重要讲话|讲话
共产党员网|https://www.12371.cn/|government|8|党建学习资源与相关视频资料|党建
高校课程思政资源平台|https://xhsz.news.cn/|government|8|课程思政示范课程与教学资源|思政
国家统计局·国家数据|https://data.stats.gov.cn/|government|9|按指标、地区和年度查询官方统计数据|统计
国家统计年鉴|https://www.stats.gov.cn/sj/ndsj/|government|9|国家统计年鉴与历年统计资料|年鉴
福建统计年鉴|https://tjj.fujian.gov.cn/xxgk/ndsj/|government|9|福建省年度统计年鉴与地方指标|福建
国家科学数据中心|https://www.escience.org.cn/data-center|government|9|各学科科学数据中心入口|数据
科学数据银行 ScienceDB|https://www.scidb.cn/|government|9|科研数据集、DOI / CSTR 与数据文件|DB
世界银行开放数据|https://data.worldbank.org/|government|9|国际经济、人口与社会发展指标|WB
知网经济社会大数据|https://data.cnki.net/|government|9|统计数据、年鉴与 AI 知数相关入口|知数
国家法律法规数据库|https://flk.npc.gov.cn/|government|10|法律法规全文、高级检索与效力状态|法
国家行政法规库|https://www.gov.cn/zhengce/xzfgk/|government|10|行政法规查询与原文阅读|法规
司法部行政法规库|http://xzfg.moj.gov.cn/search2.html|government|10|材料提供的行政法规检索入口|司法
国家规章库|https://www.gov.cn/zhengce/xxgk/gjgzk/index.htm|government|10|国家规章分类查询入口|规章
司法部规章库|https://www.moj.gov.cn/pub/sfbgw/gwygzk/index.html|government|10|司法部提供的规章查询入口|规章
人民法院案例库|https://rmfyalk.court.gov.cn/|government|10|司法案例与类案检索|案例
最高人民法院公报|http://gongbao.court.gov.cn/|government|10|法院公报与相关案例|公报
中国执行信息公开网|http://zxgk.court.gov.cn/|government|10|执行、失信被执行人与限制消费信息|执行
中国庭审公开网|http://tingshen.court.gov.cn/|government|10|公开庭审视频资源|庭审
中国裁判文书网|https://wenshu.court.gov.cn/|government|10|公开裁判文书与判决检索|文书
中国法律知识资源总库|https://lawpro.cnki.net/|government|10|法学论文、法律法规与司法案例|CN
全国标准信息平台|https://std.samr.gov.cn/gb|government|11|国家、行业与地方标准信息查询|标准
国家标准全文公开|https://openstd.samr.gov.cn/|government|11|标准号、状态与公开标准原文|GB
食品安全标准查询|https://sppt.cfsa.net.cn:8086/db|government|11|食品安全标准相关查询入口|食品
食品添加剂标准查询|http://gb2760.cfsa.net.cn/|government|11|食品添加剂相关标准查询|食品
食品安全标准资料库|https://sppt.cfsa.net.cn:8087/db|government|11|材料列出的食品安全标准资料库|标准
生态环境标准|https://www.mee.gov.cn/ywgz/fgbz/bz/|government|11|生态环境部标准与规范资源|环境
工程建设标准公告|https://www.mohurd.gov.cn/gongkai/fdzdgknr/bzgg/index.html|government|11|住房城乡建设部标准公告|建设
国家商标查询|https://sbj.cnipa.gov.cn/sbj/sbcx|government|11|商标名称、申请人与注册信息|商标
中国专利公布公告|http://epub.cnipa.gov.cn/|government|12,33|中国专利公告、说明书与附图|专利
专利检索及分析|https://pss-system.cponline.cnipa.gov.cn/|government|12|国家知识产权局专利检索与分析|专利
美国专利 PPUBS|https://www.uspto.gov/patents/search/patent-public-search|government|12|美国专利商标局专利搜索|US
Espacenet|https://ie.espacenet.com/|government|12|欧洲专利局国际专利检索|EP
WIPO PATENTSCOPE|https://patentscope2.wipo.int/search/en/search.jsf|government|12|世界知识产权组织专利检索|WO
国家知识产权局|https://www.cnipa.gov.cn/|government|12|专利、商标与地理标志政务服务|IP
地理标志产品查询|https://ggfw.cnipa.gov.cn/dlbzsq/dbQuery|government|12|地理标志产品与相关公告|地标
中国互联网联合辟谣平台|https://www.piyao.org.cn/|government|13|信息查证、辟谣资讯与事实核对|辟谣
辟谣信息查证|https://www.piyao.org.cn/pysjk/frontsql.htm|government|13|检索辟谣信息并按分类筛选|查证
国家卫生健康委|https://www.nhc.gov.cn/|government|14|医卫服务与医师执业相关信息入口|卫健
国家药监局数据查询|https://www.nmpa.gov.cn/datasearch/home-index.html|government|14|药品、化妆品与医疗器械信息查询|药监
CHKD AI|https://chkd.cnki.net/ai/|government|14|医学文献、智能伴读与 PICO 分析|医研
中国教育考试网|https://www.neea.edu.cn/|government|15|英语四六级、计算机等级和教师资格考试|考试
中国研究生招生信息网|https://yz.chsi.com.cn/|government|15|研究生招生、专业目录与专项计划|研招
国家大学生就业服务平台|https://www.ncss.cn/|government|15|高校毕业生招聘与就业信息|就业
国际组织实习任职平台|https://gj.ncss.cn/|government|15|国际组织实习与任职信息|国际
全国大学生创业服务网|https://cy.ncss.cn/|government|15|创业资源、项目与投资人信息|创业
学信网|https://www.chsi.com.cn/|government|16|学历、学位与相关验证服务|学信
证券从业人员查询|https://gs.sac.net.cn/pages/registration/new-sac-publicity-org.html|government|16|中国证券业协会人员信息公示|证券
基金从业人员查询|https://www.amac.org.cn/fwdt/wyc/jgcprycx/rycx|government|16|基金业协会资格注册信息|基金
银行业资格查询|https://www.china-cba.net/Index/lists/catid/31.html|government|16|银行从业资格考试与证书相关入口|银行
注册会计师查询|https://cmis.cicpa.org.cn/|government|16|注册会计师及事务所信息|CPA
律师执业诚信公示|https://credit.acla.org.cn/|government|16|律师执业信息与诚信公示|律师
中国记者网|https://press.nppa.gov.cn/|government|16|记者证相关信息查询|记者
中国大学 MOOC|https://www.icourse163.org/|learning|17|大学开放课程、课程大纲与视频|慕课
学堂在线|https://www.xuetangx.com/|learning|17|在线课程与开放学习资源|学堂
智慧树|https://www.zhihuishu.com/|learning|17|在线课程与学习资源平台|智慧
学银在线|https://www.xueyinonline.com/|learning|17|开放课程与在线学习|学银
高等教育智慧教育平台|https://higher.smartedu.cn/|learning|17|国家高等教育课程与教学资源|高教
职业教育智慧教育平台|https://vocational.smartedu.cn/|learning|17|职业教育专业课程与资源|职教
终身教育智慧教育平台|https://lifelong.smartedu.cn/|learning|17|终身学习与继续教育资源|终身
中小学智慧教育平台|https://basic.smartedu.cn/|learning|17|中小学课程与教学资源|基础
虚拟仿真实验教学平台|http://www.ilab-x.com/|learning|17|虚拟仿真实验教学课程共享|iLab
爱课程·视频公开课|https://www.icourses.cn/courseInfo?courseIndex=3&courseType=2&courseTypeId=2|learning|17|高校视频公开课入口|课程
爱课程·资源共享课|https://www.icourses.cn/courseInfo?courseIndex=4&courseType=1&courseTypeId=1|learning|17|精品资源共享课程入口|课程
网易公开课|https://open.163.com/|learning|17|视频公开课与演讲学习资源|网易
信息素养公益讲座|https://suyang.zxhnzq.com/lecture|learning|18|高校信息素养教育数据库直播讲座|素养
知网学术大讲堂|https://k.cnki.net/home|learning|18|学术讲座与视频学习资源|讲堂
万方视频|https://video.wanfangdata.com.cn/|learning|18|学术视频与专题学习资源|万方
学习强国|https://www.xuexi.cn/|learning|18|主题学习与视频资源|学习
一席|https://www.yixi.tv/|learning|18|中文演讲与思想分享视频|一席
TED|https://www.ted.com/|learning|18|国际演讲与视频学习资源|TED
小红书|https://www.xiaohongshu.com/|learning|2,18|学习经验、AI 教程与资源发现|红书
哔哩哔哩|https://www.bilibili.com/|learning|2,18,45|学习视频、工具教程与实操演示|B站
知乎|https://www.zhihu.com/|learning|2,18|学习问答、工具经验与知识讨论|知乎
知乎直答|https://zhida.zhihu.com/|learning|18|知乎 AI 搜索与知识问答|直答
CSDN|https://www.csdn.net/|learning|2|编程、AI 与技术学习资源|C
HathiTrust|https://www.hathitrust.org/|learning|19|数字图书馆与可公开阅读的电子书|HT
Cambridge Core|https://www.cambridge.org/core|academic|19,24|剑桥学术期刊与开放电子书|CUP
Oxford Academic·图书|https://academic.oup.com/books|learning|19|牛津学术电子书与 OA 资源|OUP
NCBI Bookshelf|https://www.ncbi.nlm.nih.gov/books/|learning|19|生命科学与医卫领域开放电子书|NCBI
国家图书馆|https://www.nlc.cn/|learning|20,23,30|馆藏目录、数字资源与读者服务|国图
美国国会图书馆|https://www.loc.gov/|learning|20,30|数字图书、地图与馆藏资源|LOC
中华古籍资源库|http://read.nlc.cn/thematDataSearch/toGujiIndex|learning|20|国家图书馆中华古籍在线资源|古籍
民国时期文献库|http://read.nlc.cn/specialResourse/minguoIndex|learning|20|民国时期图书与文献在线阅览|民国
ScienceDirect|https://www.sciencedirect.com/|academic|21,24,31,32,35,36|国际期刊论文与学术全文资源|SD
Wiley Online Library|https://onlinelibrary.wiley.com/|academic|21,24,31,32,33,35,36|外文期刊、学术图书与高级检索|W
Taylor & Francis|https://www.tandfonline.com/|academic|21,24,31,32,35,36|外文期刊论文与开放获取资源|T&F
ACM Digital Library|https://dl.acm.org/|academic|21,24,31,32,33,36|计算机科学文献与会议论文|ACM
ASME Digital Collection|https://asmedigitalcollection.asme.org/|academic|21|机械工程期刊与学术文献|ASME
Nature|https://www.nature.com/|academic|21|Nature 现刊、过刊与文章查询|N
Cell|https://www.cell.com/|academic|21|Cell 系列期刊与文章查询|Cell
Science|https://www.science.org/journal/science|academic|21|Science 现刊、过刊与研究论文|S
IEEE 会议信息|https://www.ieee.org/conferences/index.html|academic|22|会议、征稿与提交截止日期|IEEE
知网中国学术会议网|https://conf.cnki.net/Home|academic|22|学术会议通知与相关信息|会议
国家图书馆博士论文|http://read.nlc.cn/allSearch/searchList?searchType=65|academic|23|博士论文检索与资源获取入口|博士
MIT Theses|https://dspace.mit.edu/|academic|23|麻省理工学位论文与机构库|MIT
DOAJ|https://doaj.org/|academic|24|开放获取期刊目录与文献资源|DOAJ
OALIB|https://www.oalib.com/|academic|24|开放获取文献检索|OA
arXiv|https://arxiv.org/|academic|24|预印本检索、标识与版本全文|arX
ChinaXiv|https://www.chinaxiv.org/|academic|24|中国科研预印本资源|CX
medRxiv|https://www.medrxiv.org/|academic|24|医学领域预印本与版本全文|med
Oxford Academic·期刊|https://academic.oup.com/journals|academic|24|牛津学术期刊与 OA 文献|OUP
IOPscience|https://iopscience.iop.org/|academic|24|物理及相关领域学术文献|IOP
JSTOR|https://www.jstor.org/|academic|24|学术期刊、图书与开放内容|J
BioOne|https://bioone.org/|academic|24|生物与环境科学期刊资源|BIO
抗战与近代中日关系文献|https://www.modernhistory.org.cn/|academic|24|近代历史相关数字文献|历史
国家哲学社会科学文献中心|https://www.ncpssd.cn/|academic|24|哲学社会科学免费文献资源|社科
国家社科基金项目库|http://fz.people.com.cn/skygb/sk/index.php/index/index/4541|academic|25|社科项目立项、负责人和结项信息|社科
自然科学基金知识门户|https://kd.nsfc.cn/|academic|25|自科项目、结题与科研成果|NSFC
百度学术|https://xueshu.baidu.com/|systems|26|学术文献发现、引用与获取渠道|学术
PubMed|https://pubmed.ncbi.nlm.nih.gov/|systems|26,31,32,33,35,36,47|生物医学文献、字段检索与追踪告警|PM
PubScholar|https://pubscholar.cn/|systems|26|公益学术资源发现与全文获取渠道|PS
国家科技图书文献中心|https://www.nstl.gov.cn/|systems|26|科技文献检索与资源获取服务|NSTL
阿里巴巴矢量图标库|https://www.iconfont.cn/|systems|27|矢量图标检索与设计素材|icon
Unsplash|https://unsplash.com/|systems|27|摄影图片与图片素材检索|U
Pixabay|https://pixabay.com/|systems|27|图片、视频和其他创作素材|P
知网学术图片库|https://image.cnki.net/AI|systems|27|学术图片检索、对比与图片解析|图
SciDraw|https://scidraw.io/|systems|27|科学写作插图与科研绘图素材|Sci
SMART 医学素材|https://smart.servier.com/|systems|27|Servier 医学矢量插图资源|医图
百度图片|https://image.baidu.com/|systems|27|关键词图片搜索与以图搜图|图
搜狗图片|https://pic.sogou.com/|systems|27|图片检索与图片识别入口|搜狗
360 图片|https://image.so.com/|systems|27|图片检索与以图搜图入口|360
必应图片|https://www.bing.com/images|systems|27|Bing 图片搜索与视觉检索|Bing
优设导航|https://hao.uisdc.com/|systems|28|设计工具、素材与网站资源导航|优设
HIPPTER|http://www.hippter.com/|systems|28|PPT 与设计资源导航|Hi
奎章阁·古典文献导航|https://www.wenxianxue.cn/|systems|28|古籍全文和古典文献资源导航|古籍
AI 工具集|https://ai-bot.cn/|systems|28|按用途发现 AI 工具与智能体|AI
百度指数|https://index.baidu.com/v2/index.html|systems|29|关键词搜索趋势、地区与人群画像|指数
抖音指数（原巨量算数）|https://trendinsight.oceanengine.com/|systems|29|内容趋势与关键词指数分析|抖音
IEEE Xplore|https://ieeexplore.ieee.org/Xplore/home.jsp|retrieval|31,32,35,36|工程技术论文、高级检索与字段筛选|IEEE
SPIE Digital Library|https://www.spiedigitallibrary.org/|retrieval|31|光学与光子学文献高级检索|SPIE
百度高级搜索|https://www.baidu.com/gaoji/advanced.html|retrieval|37|站点、文件类型与关键词位置限定|百度
搜狗搜索|https://www.sogou.com/|retrieval|37|网页检索与高级搜索入口|搜狗
360 搜索|https://www.so.com/|retrieval|37|网页检索与高级搜索入口|360
腾讯文档|https://docs.qq.com/|knowledge|38|在线文档、思维导图与协作|腾讯
WPS|https://www.wps.cn/|knowledge|38,45|办公文档、思维导图与论文排版|WPS
有道云笔记|https://note.youdao.com/|knowledge|38|笔记管理、内容收藏与脑图|笔记
问卷星|https://www.wjx.cn/|knowledge|38|问卷设计、回收与结果统计|问卷
小恐龙公文排版助手|https://gw.xkonglong.com/|knowledge|39|Word / WPS 公文排版插件|排版
雨课堂|https://www.yuketang.cn/|knowledge|39|PPT 互动教学、题目与课堂插件|雨
OfficeAI 助手|https://www.office-ai.cn/|knowledge|39|Word、Excel 与 WPS 智能办公插件|OA
QQ|https://im.qq.com/|knowledge|40|桌面客户端、截图、贴图与录屏|QQ
LICEcap|https://www.cockos.com/licecap/|knowledge|40|屏幕操作录制为 GIF 动图|GIF
云展网 PDF 工具|https://www.yunzhan365.com/tools/pdf-to-word|knowledge|41|PDF 转换、合并、拆分与压缩|PDF
新闻出版署期刊查询|https://www.nppa.gov.cn/bsfw/cyjghcpcx|writing|42|期刊信息与正规出版资格查询|期刊
CNKI 写作投稿|https://xztg.cnki.net/|writing|42|学术热点、选题分析与智能选刊|投稿
万方科研诚信培训|https://cx.wanfangdata.com.cn/e-training|writing|43|科研诚信培训、公益讲座与学习资源|诚信
Zotero|https://www.zotero.org/|research|46|文献收集、整理、注释与引用管理|Z
Mendeley|https://www.mendeley.com/|research|46|文献管理、题录添加与学术引用|M
知网研学 E-study|https://x.cnki.net/web/search/#/down|research|46|研学桌面端、文献导入与阅读管理|研学
EndNote|https://endnote.com/|research|46|文献管理工具，材料仅要求认知|EN
NoteExpress|https://www.inoteexpress.com/|research|46|文献管理工具，材料仅要求认知|NE
Apache ECharts|https://echarts.apache.org/zh/index.html|research|49|可视化图表、示例与 JavaScript 代码|EC
微词云|https://www.weiciyun.com/|research|49|文本分词、词频统计与词云生成|词云
赛特新思|https://www.citexs.com/Paperpicky|research|50|文献调研与可视化分析|CX
CiteSpace|https://citespace.podia.com/|research|50|文献知识图谱工具与使用介绍|CS
VOSviewer|https://www.vosviewer.com/|research|50|构建文献计量与关键词网络|VOS
船政学院图书馆|http://www.fjcpc.edu.cn/tsg/|campus||图书馆服务、馆藏查询与数字资源|船政
校外数字资源访问|https://xwfw.fjcpc.edu.cn/user/caslogin|campus||学校统一认证入口，按学校权限访问|校外
福建信息素养大赛|https://fj.zhixinst.com/|campus||2026 福建省大学生信息素养大赛入口|赛事
高校信息素养教育数据库|https://suyang.zxhnzq.com/main.aspx|campus||信息素养课程与练习，机构码以学校为准|素养
读秀学术搜索|https://www.duxiu.com/|academic|30|图书检索与书目信息，按机构权限使用|读秀
'''
resources=[]
def add(name,url,category,mods,description,mark='',kind='website',source='两份备赛资料',originalUrl=None):
 parsed=urlsplit(url)
 assert parsed.scheme in ('http','https') and parsed.hostname,(name,url)
 cats=[category]+[moduleCategory[n] for n in mods if moduleCategory[n]!=category]
 cats=list(dict.fromkeys(cats))
 entry={'id':f'r{len(resources)+1:03}','name':name,'url':url,'categories':cats,'modules':sorted(set(mods)),'description':description,'mark':mark,'kind':kind,'source':source}
 if originalUrl:entry['originalUrl']=originalUrl
 resources.append(entry)
for row in seed.strip().splitlines():
 name,url,cat,nums,desc,mark=row.split('|');add(name,url,cat,[int(n) for n in nums.split(',') if n],desc,mark)
# The normative texts are labeled from the actual source PDF, preserving original deep links.
normativeNames=['生成式 AI 服务管理暂行办法','生成式 AI 服务安全基本要求','AI 拟人化互动服务管理办法','四川大学 AI 工具应用规范','中科院 AI 科研诚信提醒','上海交大教育教学 AI 规范','学术出版 AIGC 使用边界指南','UNESCO 人工智能伦理建议书','UNESCO 生成式 AI 教育研究指南','UNESCO 学生 AI 能力框架','UNESCO 教师 AI 能力框架','欧盟 AI 法中译本']
normativeLinks=[]
for annotation in pdf.pages[5].get('/Annots',[]):
 uri=annotation.get_object().get('/A',{}).get('/URI')
 if uri and 'xxsuyang' not in str(uri) and str(uri) not in normativeLinks:normativeLinks.append(str(uri))
assert len(normativeLinks)==len(normativeNames)
for name,url in zip(normativeNames,normativeLinks):add(name,url,'ai',[1],'材料指定的 AI 伦理与应用规范，阅读原文核对适用范围','规范','document','命题范围PDF第6页')
seen=set()
for pageNumber,page in enumerate(pdf.pages,1):
 num=pageToModule.get(pageNumber)
 if not num:continue
 for annotation in page.get('/Annots',[]):
  uri=str(annotation.get_object().get('/A',{}).get('/URI',''))
  if not uri or uri in seen:continue
  seen.add(uri)
  if 'xxsuyang.com/course/' in uri:
   add(f'{modules[num]} · 参考课程',uri,moduleCategory[num],[num],'命题范围材料提供的课程链接，按需观看赛题讲解','课','course',f'命题范围PDF第{pageNumber}页')
  elif 'mp.weixin.qq.com/' in uri:
   name=f'{modules[num]} · 参考文章'
   # Keep the exact material URL, not a fabricated title for the linked article.
   add(name,uri,moduleCategory[num],[num],'材料推荐的使用指南或平台介绍，前往原文阅读','文','course',f'命题范围PDF第{pageNumber}页')
  elif 'eci.elsevier.cn/resource/LeapSpace' in uri:
   add('LeapSpace 培训教程',uri,'ai',[5],'爱思唯尔提供的科研 AI 平台培训资料','课','course',f'命题范围PDF第{pageNumber}页')
  elif 'GB%20T%207714' in uri:
   add('GB/T 7714—2025 原文',uri,'writing',[44],'命题范围材料链接的参考文献著录标准 PDF','GB','document',f'命题范围PDF第{pageNumber}页')
add('GitHub 中文文档','https://docs.github.com/zh','ai',[7],'仓库、协作、版本与开源项目使用说明','GH','document','命题范围PDF第14页')
add('ONNX 开源项目','https://github.com/onnx/onnx/tree/main/LICENSES','ai',[7],'材料样题指定的项目许可证目录','ONNX','document','命题范围PDF第15页')
# Platform URLs omitted from the text are linked to their official entrypoint.
extraNotes=[
 {'name':'微信指数','modules':[29],'entry':'在微信中搜索“微信指数”','reason':'材料中的微信内入口，没有独立网页链接'},
 {'name':'国家反诈中心 APP','modules':[13],'entry':'在手机官方应用商店搜索“国家反诈中心”','reason':'APP 功能需在手机中使用'},
 {'name':'微信辟谣助手 / 腾讯较真辟谣','modules':[13],'entry':'在微信中搜索对应小程序','reason':'材料中的小程序入口'},
 {'name':'全民较真 / 科学辟谣 / 微博辟谣','modules':[13],'entry':'在对应平台搜索官方账号','reason':'材料中的公众号或账号名称'},
 {'name':'WeLink 图书馆','modules':[],'entry':'WeLink 大厅 → 图书馆，绑定本人学号','reason':'校内移动服务，不伪造直接登录链接'},
 {'name':'云班课','modules':[],'entry':'云班课搜索班课号4725134，先核对学校最新通知','reason':'材料截图给出的班课号'},
]
data={'title':'素养聚合','updated':'2026-09-28','categories':[{'id':i,'name':n,'short':s} for i,n,s in categories],'modules':modules,'resources':resources,'appOnlyEntries':extraNotes}
# Resource priorities keep everyday entrypoints first without hiding the reference material.
priority={'中国知网':0,'万方数据':1,'维普':2,'DeepSeek':3,'豆包':4,'腾讯元宝':5,'Kimi':6,'智谱清言':7,'千问（通义）':8,'CNKI AI':9,'国家统计局·国家数据':10,'国家法律法规数据库':11}
resources.sort(key=lambda r:(0 if r['kind']=='website' else 1,priority.get(r['name'],99),int(r['id'][1:])))
dist=PROJECT/'dist';dist.mkdir(exist_ok=True)
(dist/'resources.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
(dist/'resources.js').write_text('window.LITERACY_DATA = '+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n',encoding='utf-8')
print(f'Created {len(resources)} links, {len(modules)} module labels and {len(extraNotes)} app-only entry notes.')
print('Kinds:',{k:sum(r['kind']==k for r in resources) for k in ['website','course','document']})
