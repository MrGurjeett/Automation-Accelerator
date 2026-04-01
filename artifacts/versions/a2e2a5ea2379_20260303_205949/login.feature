Feature: Login

  Scenario Outline: Login — Flow 1
    Given I navigate to "Login Page"
    When I fill "Email" with "<Email>"
    When I fill "Password" with "<Password>"
    And I click "Login Button"
    Then I verify "Dashboard Message" shows "<Dashboard_Message_expected>"

    Examples:
      | TC_ID | Email | Password | Dashboard_Message_expected |
      | TC01 | autotest1772551670@test.com | AutoPass@123 | Contact List |

  Scenario Outline: Login — Flow 2
    Given I navigate to "Login Page"
    When I fill "Email" with "<Email>"
    When I fill "Password" with "<Password>"
    And I click "Login Button"
    Then I verify "Error Message" shows "<Error_Message_expected>"

    Examples:
      | TC_ID | Email | Password | Error_Message_expected |
      | TC02 | wrong@mail.com | WrongPass | Incorrect username or password |
