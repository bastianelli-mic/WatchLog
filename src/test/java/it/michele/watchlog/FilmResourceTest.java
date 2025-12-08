package it.michele.watchlog;

import io.quarkus.test.junit.QuarkusTest;
import it.michele.watchlog.service.FilmService;
import jakarta.inject.Inject;
import org.junit.jupiter.api.Test;

import static io.restassured.RestAssured.given;
import static org.hamcrest.CoreMatchers.containsString;

@QuarkusTest
public class FilmResourceTest {

    @Inject
    FilmService filmService;

    @Test
    void testGetFilm(){
        given()
            .when().get("/film/get/1")
            .then()
            .statusCode(200)
            .body(containsString("Star wars"));
    }
}
