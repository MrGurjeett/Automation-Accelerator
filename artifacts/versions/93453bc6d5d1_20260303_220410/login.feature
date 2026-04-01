Feature: Login

  Scenario Outline: Login — Flow 1
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    When I fill "Password" with "<Password>"
    And I click "Submit Button"
    Then I verify "Success Message" shows "<Success_Message_expected>"

    Examples:
      | TC_ID | Username | Password | Success_Message_expected |
      | TC01 | student | Password123 | Logged In Successfully |

  Scenario Outline: Login — Flow 2
    Given I navigate to "Login Page"
    When I fill "Username" with "<Username>"
    When I fill "Password" with "<Password>"
    And I click "Submit Button"
    Then I verify "Error Message" shows "<Error_Message_expected>"

    Examples:
      | TC_ID | Username | Password | Error_Message_expected |
      | TC02 | student | WrongPass | Your password is invalid! |
      | TC03 | wronguser | Password123 | Your username is invalid! |
      | TC04 | - | - | Your username is invalid! |
