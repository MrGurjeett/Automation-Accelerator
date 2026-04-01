Feature: Login

  Scenario Outline: Login — Flow 1
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    When I fill "Password" with "<Password>"
    And I click "Submit Button"
    Then I verify "Accounts Overview Title" shows "<Accounts_Overview_Title_expected>"

    Examples:
      | TC_ID | Username | Password | Accounts_Overview_Title_expected |
      | TC01 | Admin | Password@123 | Accounts Overview |
      | TC02 | john | demo | Accounts Overview |

  Scenario Outline: Login — Flow 2
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    When I fill "Password" with "<Password>"
    And I click "Submit Button"
    Then I verify "Error Message" shows "<Error_Message_expected>"

    Examples:
      | TC_ID | Username | Password | Error_Message_expected |
      | TC03 | [EMPTY] | [EMPTY] | Please enter a username and password. |

  Scenario Outline: Login — Flow 3
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    When I fill "Password" with "<Password>"
    And I click "Submit Button"
    Then I verify "Welcome Message" shows "<Welcome_Message_expected>"

    Examples:
      | TC_ID | Username | Password | Welcome_Message_expected |
      | TC04 | Admin | Password@123 | Welcome |
