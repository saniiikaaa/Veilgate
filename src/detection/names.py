"""Word lists for name detection. A first name from FIRST_NAMES followed by a capitalised word is treated as a person."""

FIRST_NAMES = frozenset(
    """
    aarav aarti aaditya abhay abhijit abhishek aditi aditya ajay akash akhil alok aman amar amit amita amrita anand ananya
    anil anita anjali ankit ankita anna anil anshul anu anupam aparna arjun arun aruna aryan asha ashish ashok atul ayush
    bharat bhavna bhavya chandra chetan deepa deepak deepika dev devika dhruv dinesh divya farhan fatima gaurav gautam gayatri
    geeta gita gopal govind gopi harish harsh hema hemant himani imran indra isha ishaan jagdish jaya jayesh jyoti kabir kajal
    kamal kamla kapil karan karthik kavita kavya kiran kishore komal krishna kumar kunal lakshmi lalit lata leela madhav madhu
    mahesh mahi manish manju manoj mansi meena meera mehul mohan mohit mukesh nandini naresh naveen neeraj neha nidhi nikhil
    nikita nilesh nisha nitin nitish om pankaj parth pooja prabhu pradeep prakash pranav prasad pratik preeti priya priyanka
    puja rahul raj rajan rajat rajesh rajiv rakesh ramesh rani ravi reena rekha rohan rohit roshni sachin sagar sahil sakshi
    sameer sandeep sangeeta sanjay sanjana sapna sara saurabh seema shalini shankar sharad shiv shivani shreya shruti shubham
    siddharth sita smita sneha sonal sonia sonu srinivas subhash sudhir sujata sunil sunita suresh surya sushil swati tanvi
    tarun tushar uday uma usha vaibhav vandana varun vijay vikas vikram vimal vinay vinod vishal vivek yash yogesh zoya
    aisha ahmed ali amina farah hassan ibrahim khalid layla mohammed muhammad omar rashid sana yusuf zainab
    aaron adam adrian alan albert alex alexander alice alicia amanda amy andrea andrew angela ann anna anthony arthur ashley
    barbara ben benjamin beth betty bill bob bobby brandon brenda brian bruce carl carlos carol caroline catherine charles
    charlotte chris christian christina christopher cindy claire daniel david deborah dennis diana diane donald donna dorothy
    douglas edward elizabeth ella emily emma eric ethan eva evelyn frank fred gary george gerald gloria gregory hannah harold
    harry heather helen henry isabella jack jacob james jane janet jason jean jeffrey jennifer jeremy jerry jessica jill joan
    joe john jonathan joseph joshua joyce juan judith judy julia julie justin karen kate katherine kathleen keith kelly ken
    kenneth kevin kim kimberly larry laura lauren lawrence linda lisa lori louis lucy luke margaret maria marie marilyn mark
    martha martin mary matthew megan melissa michael michelle mike nancy natalie nathan nicholas nicole noah olivia pamela
    patricia patrick paul peter philip rachel ralph randy raymond rebecca richard robert roger ronald rose roy russell ruth
    ryan samantha samuel sandra sarah scott sean sharon shirley sophia stephanie stephen steve steven susan tammy teresa
    terry theresa thomas timothy tina todd tom tyler victoria vincent virginia walter wayne william willie zachary
    li wei ming chen yuki hiroshi kenji takeshi sakura mei jin hyun min ji soo
    jose miguel luis pedro pablo sofia carmen isabel ana lucia fernando ricardo diego
    ivan olga natasha dmitri sergei anya pierre jean francois claire marie hans klaus greta
    """.split()
)

# Capitalised words that are not part of a person's name (so "Patient Records" or "City Hospital" is not a name).
NOT_NAME_WORDS = frozenset(
    """
    the a an this that these those it its i we you he she they my our your his her their
    dr mr mrs ms miss mx prof shri smt sri mister doctor nurse
    patient patients record records data information details name names id number numbers history chart file files report
    reports summary summaries note notes list table query result results request response user users customer customers
    client clients employee employees staff admin administrator system support service services team teams department
    hospital clinic medical health healthcare center centre care insurance bank university college school institute
    pharmacy laboratory lab company corporation inc ltd llc pvt limited technologies solutions group association
    street road avenue lane city state country district town village area zone region
    monday tuesday wednesday thursday friday saturday sunday january february march april may june july august september
    october november december
    yes no ok okay none null true false unknown n/a hello hi hey dear sir madam regards thanks thank welcome please
    today tomorrow yesterday world all everyone everybody someone anyone
    diagnosis treatment medication prescription appointment visit address email phone mobile account card payment
    salary income balance amount total status type category role
    """.split()
)
