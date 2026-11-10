// V8: cream carries the subject, jade its surface, coral/gold its motion.
// Recursion is geometry: four Koch substitutions and four hexaflake similarities.
float geoLife(float t,float a,float b) {
    return smoothstep(a,a+0.65,t)*(1.0-smoothstep(b-0.65,b,t));
}
float geoInk(float d,float width,float aa) { return 1.0-smoothstep(width,width+aa,d); }
float geoCross(vec2 a,vec2 b) { return a.x*b.y-a.y*b.x; }
vec3 geoPigment(float along,float t) {
    float front=0.5+0.5*sin(along*PI-t*0.17);
    return mix(JADE,CORAL,smoothstep(0.58,0.95,front)*0.46);
}
void geoTrack(vec2 p,vec2 a,vec2 b,float ua,float ub,inout float d,inout float along) {
    vec2 e=b-a;
    float u=clamp(dot(p-a,e)/max(dot(e,e),0.000001),0.0,1.0);
    float q=length(p-a-u*e);
    if(q<d) { d=q; along=mix(ua,ub,u); }
}
float geoCrossing(vec2 p,vec2 a,vec2 b) {
    if((a.y>p.y)!=(b.y>p.y))
        return step(p.x,a.x+(p.y-a.y)*(b.x-a.x)/(b.y-a.y));
    return 0.0;
}
float geoTriangle(vec2 p,vec2 a,vec2 b,vec2 c,float aa) {
    float orient=sign(geoCross(b-a,c-a));
    float da=orient*geoCross(b-a,p-a)/max(length(b-a),0.0001);
    float db=orient*geoCross(c-b,p-b)/max(length(c-b),0.0001);
    float dc=orient*geoCross(a-c,p-c)/max(length(a-c),0.0001);
    float area=abs(geoCross(b-a,c-a));
    return smoothstep(-aa,aa,min(da,min(db,dc)))*smoothstep(0.0001,0.003,area);
}
vec3 geoOpening(vec2 p,float t,float aa) {
    float reveal=smoothstep(0.3,4.0,t);
    float release=smoothstep(10.6,13.7,t);
    vec3 c=vec3(0.0);
    for(int lane=0;lane<2;lane++) {
        float k=float(lane),d=100.0,along=0.0;
        vec2 previous=vec2(-6.1,-2.35-k*0.32);
        for(int j=1;j<=96;j++) {
            float u=min(float(j)/96.0,reveal);
            float x=mix(-6.1,6.1,u);
            float y=-2.35-k*0.32+sin(u*TAU-t*0.34+k*0.5)*(0.12+0.48*release);
            y+=release*0.62*sin(u*PI);
            vec2 current=vec2(x,y);
            geoTrack(p,previous,current,max(0.0,u-1.0/96.0),u,d,along);
            previous=current;
        }
        c+=glow(d,lane==0?0.030:0.010,lane==0?WHITE:JADE,lane==0?0.93:0.55,aa);
        c+=CORAL*geoInk(d,0.041,aa)*pow(max(0.0,1.0-abs(along-fract(t*0.085))*14.0),3.0)*0.22;
    }
    return c*(1.0-smoothstep(13.0,14.0,t));
}
vec2 geoPetalPoint(float u,float t) {
    float a=u*TAU-PI*0.5;
    float bloom=smoothstep(18.5,23.0,t);
    float knot=smoothstep(27.0,31.2,t);
    float radius=2.88*mix(1.0,0.64+0.36*cos(6.0*a),bloom);
    vec2 flower=vec2(cos(a)*mix(1.0,1.78,bloom),sin(a))*radius;
    // A (2,3) torus knot is projected from 3D into the flower's frame.
    float r=2.28+0.68*cos(3.0*a);
    vec2 projected=vec2(1.68*r*cos(2.0*a),0.72*r*sin(2.0*a)+0.78*sin(3.0*a));
    return mix(flower,projected,knot)+vec2(0.0,-0.02);
}
vec3 geoPetals(vec2 p,float t,float aa) {
    float draw=smoothstep(14.2,17.2,t);
    float fill=smoothstep(19.5,22.0,t)*(1.0-smoothstep(28.0,31.0,t));
    float knot=smoothstep(27.0,31.2,t);
    float d=100.0,along=0.0,crossings=0.0;
    vec2 previous=geoPetalPoint(0.0,t);
    for(int j=1;j<=192;j++) {
        float u=min(float(j)/192.0,draw);
        vec2 current=geoPetalPoint(u,t);
        geoTrack(p,previous,current,min(float(j-1)/192.0,draw),u,d,along);
        crossings+=geoCrossing(p,previous,current);
        previous=current;
    }
    vec3 c=JADE*0.13*mod(crossings,2.0)*fill;
    c+=glow(d,0.032,mix(WHITE,CORAL,knot*0.52),1.0,aa);
    for(int i=0;i<6;i++) {
        float u=float(i)/6.0+1.0/12.0;
        vec2 edge=geoPetalPoint(u,t);
        c+=glow(lineDistance(p,vec2(0.0,-0.02),edge),0.010,JADE,0.50*fill,aa);
    }
    float spark=fract(max(0.0,t-16.0)*0.075);
    c+=glow(length(p-geoPetalPoint(spark,t)),0.071,GOLD,0.9*draw,aa);
    return c*geoLife(t,14.0,34.0);
}
// Inverse similarities fold the four real Koch children onto the unit edge.
// theta=0 gives four collinear children; theta=PI/3 the Koch substitution.
vec2 geoKochEdge(vec2 q,float depth) {
    float metric=1.0;
    for(int k=0;k<4;k++) {
        float theta=(PI/3.0)*smoothstep(0.0,1.0,depth-float(k));
        float child=1.0/(2.0+2.0*cos(theta));
        vec2 normal=vec2(cos(theta*0.5),sin(theta*0.5));
        q.x=min(q.x,1.0-q.x);
        q-=vec2(child,0.0);
        q-=2.0*max(dot(q,normal),0.0)*normal;
        q+=vec2(child,0.0);
        q/=child;
        metric*=child;
    }
    return vec2(length(q-vec2(clamp(q.x,0.0,1.0),0.0)),q.y)*metric;
}
vec3 geoKoch(vec2 p,float t,float aa) {
    float depth=4.0*smoothstep(36.5,44.0,t);
    float push=smoothstep(44.8,47.0,t)*(1.0-smoothstep(49.0,52.0,t));
    float zoom=mix(1.0,2.85,push);
    vec2 focus=vec2(2.24,0.56)*push;
    vec2 q=p/zoom+focus;
    q.x/=1.48;
    q.y+=0.05;
    float d=100.0,ancestor=100.0,cap=0.0;
    vec2 v0=vec2(0.0,3.10),v1=vec2(2.684679,-1.55),v2=vec2(-2.684679,-1.55);
    float inside=geoTriangle(q,v0,v1,v2,aa/zoom);
    for(int side=0;side<3;side++) {
        vec2 a=side==0?v0:(side==1?v1:v2);
        vec2 b=side==0?v1:(side==1?v2:v0);
        vec2 e=b-a;
        float span=length(e);
        vec2 tangent=e/span,normal=vec2(-tangent.y,tangent.x);
        vec2 local=vec2(dot(q-a,tangent),dot(q-a,normal))/span;
        vec2 edge=geoKochEdge(local,depth);
        d=min(d,edge.x*span);
        ancestor=min(ancestor,geoKochEdge(local,max(0.0,depth-1.0)).x*span);
        cap+=step(0.0,local.x)*step(local.x,1.0)*step(0.0,local.y)
             *(1.0-smoothstep(-aa/zoom,aa/zoom,edge.y*span));
    }
    d*=zoom;
    ancestor*=zoom;
    vec3 c=JADE*0.068*min(1.0,inside+cap);
    c+=glow(ancestor,0.010,JADE,0.34*smoothstep(0.6,1.2,depth),aa);
    c+=glow(d,0.031,WHITE,1.03,aa);
    float front=exp(-pow((q.x-(t-34.0)*0.37+3.1)*1.2,2.0));
    c+=glow(d,0.039,mix(CORAL,GOLD,smoothstep(40.0,49.0,t)),0.38*front,aa);
    return c*geoLife(t,34.0,54.0);
}
vec2 geoWavePoint(float u,float t) {
    float a=TAU*u;
    float phase=(t-54.0)*0.82;
    float unroll=smoothstep(58.6,63.2,t);
    vec2 circle=2.75*vec2(cos(a+phase),sin(a+phase));
    float h3=smoothstep(64.0,66.4,t),h5=smoothstep(67.0,69.3,t),h7=smoothstep(70.0,71.8,t);
    float wave=sin(a+phase)+h3*sin(3.0*(a+phase))/3.0
              +h5*sin(5.0*(a+phase))/5.0+h7*sin(7.0*(a+phase))/7.0;
    return mix(circle,vec2(mix(-5.55,5.55,u),2.13*wave),unroll);
}
vec3 geoWaves(vec2 p,float t,float aa) {
    float unroll=smoothstep(58.6,63.2,t);
    float grid=smoothstep(54.0,55.0,t)*(1.0-smoothstep(62.5,65.0,t));
    vec3 c=vec3(0.0);
    c+=glow(lineDistance(p,vec2(-6.0,0.0),vec2(6.0,0.0)),0.010,JADE,0.34,aa);
    c+=glow(lineDistance(p,vec2(0.0,-3.0),vec2(0.0,3.0)),0.010,JADE,0.26*grid,aa);
    float d=100.0,along=0.0;
    vec2 previous=geoWavePoint(0.0,t);
    for(int j=1;j<=160;j++) {
        float u=float(j)/160.0;
        vec2 current=geoWavePoint(u,t);
        geoTrack(p,previous,current,u-1.0/160.0,u,d,along);
        previous=current;
    }
    c+=glow(d,0.032,WHITE,1.02,aa);
    float separate=smoothstep(63.0,65.0,t)*(1.0-smoothstep(70.3,73.0,t));
    for(int lane=0;lane<2;lane++) {
        float n=lane==0?3.0:5.0;
        float sd=100.0;
        vec2 last=vec2(-5.55,2.13*sin(n*(t-54.0)*0.82)/n);
        for(int j=1;j<=80;j++) {
            float u=float(j)/80.0;
            vec2 v=vec2(mix(-5.55,5.55,u),2.13*sin(n*(TAU*u+(t-54.0)*0.82))/n);
            sd=min(sd,lineDistance(p,last,v)); last=v;
        }
        c+=glow(sd,0.010,lane==0?JADE:CORAL,0.54*separate,aa);
    }
    vec2 point=geoWavePoint(fract((t-54.0)*0.11),t);
    c+=glow(length(p-point),0.077,GOLD,0.95,aa);
    c+=glow(lineDistance(p,vec2(0.0),point),0.010,CORAL,0.62*(1.0-unroll),aa);
    return c*geoLife(t,54.0,74.0);
}
vec2 geoSheetPoint(float u,float v,float t) {
    float grow=smoothstep(76.5,80.5,t);
    float fold=smoothstep(80.0,85.0,t);
    float crown=smoothstep(87.0,92.0,t);
    float a=u*TAU;
    float phase=(t-74.0)*0.18;
    vec3 sheet=vec3((u*2.0-1.0)*5.50,
                    0.58*sin(a+phase)+v*1.42*grow,
                    v*1.30*sin(a*1.5+phase)*grow*fold);
    vec2 projected=vec2(sheet.x+sheet.z*0.48,sheet.y*0.88+sheet.z*0.70);
    float r=2.15+0.80*v+0.30*cos(5.0*a+phase);
    vec2 flower=vec2(1.70*r*cos(a),0.85*r*sin(a)+v*0.65*sin(5.0*a+phase));
    return mix(projected,flower,crown)+vec2(0.0,-0.05);
}
vec3 geoSheets(vec2 p,float t,float aa) {
    vec3 c=vec3(0.0);
    float grow=smoothstep(76.5,80.5,t);
    // Fifty-six large translucent facets carry the projected folds.
    for(int j=0;j<28;j++) {
        float u=float(j)/28.0,w=float(j+1)/28.0;
        vec2 a=geoSheetPoint(u,-1.0,t),b=geoSheetPoint(w,-1.0,t);
        vec2 d=geoSheetPoint(u,1.0,t),e=geoSheetPoint(w,1.0,t);
        float face=geoTriangle(p,a,b,d,aa)+geoTriangle(p,b,e,d,aa);
        float light=0.72+0.28*sin(u*TAU*2.0+(t-74.0)*0.15);
        c+=geoPigment(u,t)*face*0.095*light*grow;
    }
    for(int lane=0;lane<5;lane++) {
        float v=float(lane)*0.5-1.0;
        float d=100.0,along=0.0;
        vec2 previous=geoSheetPoint(0.0,v,t);
        for(int j=1;j<=80;j++) {
            float u=float(j)/80.0;
            vec2 current=geoSheetPoint(u,v,t);
            geoTrack(p,previous,current,u-1.0/80.0,u,d,along); previous=current;
        }
        bool edge=(lane==0 || lane==4);
        float visible=lane==2?1.0:grow;
        c+=glow(d,edge?0.030:(lane==2?0.028:0.010),edge?WHITE:JADE,
                (edge?0.93:(lane==2?0.68:0.45))*visible,aa);
    }
    for(int j=0;j<12;j++) {
        float u=float(j)/12.0;
        float d=100.0;
        vec2 last=geoSheetPoint(u,-1.0,t);
        for(int k=1;k<=6;k++) {
            vec2 current=geoSheetPoint(u,float(k)/3.0-1.0,t);
            d=min(d,lineDistance(p,last,current)); last=current;
        }
        c+=glow(d,0.010,mix(JADE,CORAL,float(j)/11.0),0.36*grow,aa);
    }
    return c*geoLife(t,74.0,96.0);
}
float geoHexagon(vec2 p) {
    p=abs(p);
    return max(p.y,max(p.x*0.8660254+p.y*0.5,p.x*0.8660254-p.y*0.5))-0.8660254;
}
vec3 geoStar(vec2 p,float t,float aa) {
    float assembly=smoothstep(96.0,99.5,t);
    float depth=1.0+3.0*smoothstep(99.5,108.0,t);
    vec2 q=vec2(p.x/1.66,p.y+0.02)/3.10;
    float scale=3.10,valid=1.0;
    vec3 c=vec3(0.0);
    // Seven parent pieces assemble; each has seven ratio-1/3 children.
    for(int level=0;level<4;level++) {
        float k=float(level);
        float spread=level==0?mix(1.30,2.0/3.0,assembly):2.0/3.0;
        vec2 chosen=vec2(0.0);
        float nearest=geoHexagon(q*3.0)/3.0;
        float branch=0.0;
        for(int child=0;child<6;child++) {
            float a=float(child)*PI/3.0;
            vec2 center=vec2(cos(a),sin(a))*spread;
            float candidate=geoHexagon((q-center)*3.0)/3.0;
            if(candidate<nearest) { nearest=candidate; chosen=center; branch=float(child+1); }
        }
        float reveal=smoothstep(k+0.05,k+0.75,depth);
        float next=smoothstep(k+1.05,k+1.75,depth);
        float sd=nearest*scale;
        float ink=1.0-smoothstep(-aa,aa,sd);
        float width=level==0?0.030:0.010;
        float strength=level==0?0.82:0.60;
        vec3 hue=mix(CORAL,GOLD,clamp((t-99.0)*0.085+branch*0.045,0.0,1.0));
        float violet=smoothstep(106.0,109.5,t)*step(4.5,branch)*0.32;
        hue=mix(hue,VIOLET,violet);
        c+=hue*ink*(0.075-0.010*k)*valid*reveal;
        c+=glow(abs(sd),width,level==0?mix(WHITE,GOLD,0.38):hue,
                strength*valid*reveal*(1.0-0.34*next),aa);
        valid*=ink;
        q=(q-chosen)*3.0;
        scale/=3.0;
    }
    return c*geoLife(t,96.0,112.0);
}
vec3 geoClosing(vec2 p,float t,float aa) {
    float settle=smoothstep(112.0,115.0,t);
    float d=100.0,along=0.0;
    vec2 previous=vec2(-5.9,-1.78);
    for(int j=1;j<=96;j++) {
        float u=float(j)/96.0;
        vec2 current=vec2(mix(-5.9,5.9,u),-1.78+(1.0-settle)*0.62*sin(u*TAU));
        geoTrack(p,previous,current,u-1.0/96.0,u,d,along); previous=current;
    }
    vec3 c=glow(d,0.031,WHITE,0.86*smoothstep(112.0,112.8,t),aa);
    c+=glow(d,0.039,GOLD,0.10*settle,aa);
    return c;
}
vec3 geometryAct(vec2 p,float t,float aa) {
    if(t<14.0) return geoOpening(p,t,aa);
    if(t<34.0) return geoPetals(p,t,aa);
    if(t<54.0) return geoKoch(p,t,aa);
    if(t<74.0) return geoWaves(p,t,aa);
    if(t<96.0) return geoSheets(p,t,aa);
    if(t<112.0) return geoStar(p,t,aa);
    return geoClosing(p,t,aa);
}
