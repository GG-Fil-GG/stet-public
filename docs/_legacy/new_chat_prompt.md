### **Prompt for New Chat (Technical Lead & Sprint Manager)**

**System/Role:**
You are a Senior Python Architect and Technical Project Manager. I am a "vibe coder" (I understand logic but need help with syntax and structure).

**The Mission:**
I have a freelance medical writing project starting **Jan 5th**. I need a **tool** ready by **Jan 4th** to automate the process of addressing reviewer comments in Word manuscripts.

**The Assets I Have:**

1. **`extract_comments_final.py`:** A working script that uses `zipfile` and `xml.etree` to parse `.docx` files. It extracts comments, authors, dates, and the *context* (referenced text). It currently prints a human-readable report. This script works fairly well to identify non-resolved comments, but does pick up resolved comments sometimes.
2. **`draft_spec.md`:** A specification for a future "Local Web App" version of this tool. This is the long-term goal, but **NOT** the goal for this week.

**Your First Instruction:**

Analyze `extract_comments_final.py` and `draft_spec.md` and help me determine the **goal** and, based on that goal, the **schedule** for this week.

- The goal should be based on what can be realistically accomplished by a human vibe coder working in conjunction with AI, working 7-8 hours per day, Monday to Friday and leaving Saturday and Sunday as buffer. The goal should also be based on the idea that the tool should be operational - not partially completed, with functionality that is only partially implemented or usable. I would like to move as close as possible from the current script to what is described in the spec - but realistically, an intermediate working state is what I anticipate.

- The schedule should represent a day-by-day plan of how to get to the goal.

Note: It is already Monday, about 10 am now.
