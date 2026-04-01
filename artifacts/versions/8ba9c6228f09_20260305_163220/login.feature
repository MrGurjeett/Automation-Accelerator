Feature: Login

  Scenario Outline: Login — Flow 1
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    When I fill "Password" with "<Password>"
    And I click "Login Button"
    Then I verify "Accounts Overview Title" shows "<Accounts_Overview_Title_expected>"

    Examples:
      | TC_ID | Username | Password | Accounts_Overview_Title_expected |
      | TC01 | Admin | Password@123 | Accounts Overview |

  Scenario Outline: Login — Flow 2
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    When I fill "Password" with "<Password>"
    And I click "Login Button"
    Given I navigate to "Transfer Funds"
    When I select "Fromaccountid" with "<Fromaccountid>"
    When I select "Toaccountid" with "<Toaccountid>"
    When I fill "Amount" with "<Amount>"
    And I click "Submit Button"
    Given I navigate to "Transfer Funds"

    Examples:
      | TC_ID | Username | Password | Fromaccountid | Toaccountid | Amount |
      | TC02 | Admin | Password@123 | first | second account | 100 |

  Scenario Outline: Login — Flow 3
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    When I fill "Password" with "<Password>"
    And I click "Login Button"
    Given I navigate to "Bill Pay"
    When I fill "Payee.name" with "<Payee.name>"
    When I fill "Customer.address.city" with "<Customer.address.city>"
    When I fill "Amount" with "<Amount>"
    Given I navigate to "Bill Pay"
    Then I verify "Success Message" shows "<Success_Message_expected>"

    Examples:
      | TC_ID | Username | Password | Payee.name | Customer.address.city | Amount | Success_Message_expected |
      | TC03 | Admin | Password@123 | John | New York | 50 | payment success |

  Scenario Outline: Login — Flow 4
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    When I fill "Password" with "<Password>"
    And I click "Login Button"
    Given I navigate to "Request Loan"
    When I fill "Amount" with "<Amount>"
    When I fill "Downpayment" with "<Downpayment>"
    Given I navigate to "Request Loan"
    Then I verify "Request Loan" shows "<Request_Loan_expected>"

    Examples:
      | TC_ID | Username | Password | Amount | Downpayment | Request_Loan_expected |
      | TC04 | Admin | Password@123 | 5000 | 500 | loan request processed |
