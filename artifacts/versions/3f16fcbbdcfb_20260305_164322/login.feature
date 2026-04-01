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
    When I select "From Account" with "<From_Account>"
    When I select "To Account" with "<To_Account>"
    When I fill "Amount" with "<Amount>"
    And I click "Submit Button"
    Then I verify "Transfer Funds" shows "<Transfer_Funds_expected>"

    Examples:
      | TC_ID | Username | Password | From_Account | To_Account | Amount | Transfer_Funds_expected |
      | TC02 | Admin | Password@123 | first | second account | 100 | confirmation |

  Scenario Outline: Login — Flow 3
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    When I fill "Password" with "<Password>"
    And I click "Login Button"
    Given I navigate to "Request Loan"
    When I fill "loan amount" with "<loan_amount>"
    When I fill "Down Payment" with "<Down_Payment>"
    Given I navigate to "Request Loan"
    Then I verify "Request Loan" shows "<Request_Loan_expected>"

    Examples:
      | TC_ID | Username | Password | loan_amount | Down_Payment | Request_Loan_expected |
      | TC04 | Admin | Password@123 | 5000 | 500 | loan request processed |
