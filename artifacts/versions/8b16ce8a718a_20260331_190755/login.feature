Feature: Login

  Scenario Outline: Login — Flow 1
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    When I fill "Password" with "<Password>"
    And I click "Login Button"
    Then I verify "Accounts Overview Title" shows "<Accounts_Overview_Title_expected>"

    Examples:
      | TC_ID | Username | Password | Accounts_Overview_Title_expected |
      | TC01 | john | demo | Accounts Overview |

  Scenario Outline: Login — Flow 2
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    When I fill "Password" with "<Password>"
    And I click "Login Button"
    Given I navigate to "Transfer Funds"
    When I fill "Amount" with "<Amount>"
    When I select "Fromaccountid" with "<Fromaccountid>"
    When I select "Toaccountid" with "<Toaccountid>"
    And I click "Transfer"
    Then I verify "Transfer" shows "<Transfer_expected>"

    Examples:
      | TC_ID | Username | Password | Amount | Fromaccountid | Toaccountid | Transfer_expected |
      | TC02 | john | demo | 100 | first | 2 | Transfer Complete |

  Scenario Outline: Login — Flow 3
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    When I fill "Password" with "<Password>"
    And I click "Login Button"
    Given I navigate to "Bill Pay"
    When I fill "Payee.name" with "<Payee.name>"
    When I fill "Payee.address.street" with "<Payee.address.street>"
    When I fill "Payee.address.city" with "<Payee.address.city>"
    When I fill "Payee.address.state" with "<Payee.address.state>"
    When I fill "Payee.address.zipCode" with "<Payee.address.zipCode>"
    When I fill "Payee.phoneNumber" with "<Payee.phoneNumber>"
    When I fill "Payee.accountNumber" with "<Payee.accountNumber>"
    When I fill "verifyAccount" with "<verifyAccount>"
    When I fill "Amount" with "<Amount>"
    And I click "Send Payment"
    Then I verify "Bill Payment Complete" shows "<Bill_Payment_Complete_expected>"

    Examples:
      | TC_ID | Username | Password | Payee.name | Payee.address.street | Payee.address.city | Payee.address.state | Payee.address.zipCode | Payee.phoneNumber | Payee.accountNumber | verifyAccount | Amount | Bill_Payment_Complete_expected |
      | TC03 | john | demo | John | 123 Main St | New York | NY | 10001 | 1234567890 | 13344 | 13344 | 50 | was successful |

  Scenario Outline: Login — Flow 4
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    When I fill "Password" with "<Password>"
    And I click "Login Button"
    Given I navigate to "Request Loan"
    When I fill "Amount" with "<Amount>"
    When I fill "Downpayment" with "<Downpayment>"
    And I click "Apply Now"
    Then I verify "Loan request has been processed" shows "<Loan_request_has_been_processed_expected>"

    Examples:
      | TC_ID | Username | Password | Amount | Downpayment | Loan_request_has_been_processed_expected |
      | TC04 | john | demo | 100 | 10 | Loan request has been processed |
